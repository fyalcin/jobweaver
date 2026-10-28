"""Shared input contracts for HTTP, scheduled collection and direct Python callers."""
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

MODEL_CHARS = 200
TEXT_CHARS = 1_000_000
KEYWORD_CHARS = 4_000
KEYWORD_PHRASES = 20
KEYWORD_PHRASE_CHARS = 500
MAX_LANES = 20
MAX_BATCH_JOBS = 300
MAX_PDF_BASE64_CHARS = 16 * 1024 * 1024  # One decoded 12 MiB PDF.

ModelName = Annotated[str, Field(max_length=MODEL_CHARS)]
Identifier = Annotated[str, Field(min_length=1, max_length=512)]
ShortText = Annotated[str, Field(max_length=200)]
SourceLabel = Annotated[str, Field(max_length=300)]  # A 200-character probe tag plus username.
SourceText = Annotated[str, Field(max_length=TEXT_CHARS)]
Instruction = Annotated[str, Field(max_length=20_000)]
PdfBase64 = Annotated[str, Field(max_length=MAX_PDF_BASE64_CHARS)]
ScrapeSource = Literal['linkedin-apify', 'karriere-apify', 'company-feeds']
Hours = Annotated[int, Field(strict=True, ge=1, le=720)]
Distance = Annotated[int, Field(strict=True, ge=1, le=200)]
LinkedinLimit = Annotated[int, Field(strict=True, ge=1, le=500)]
KarriereLimit = Annotated[int, Field(strict=True, ge=1, le=200)]


def keyword_list(value: Any) -> list[str]:
    """Accept the existing comma-separated string or list, without coercing objects."""
    if value is None:
        return []
    if isinstance(value, str):
        if len(value) > KEYWORD_CHARS:
            raise ValueError(f'keywords exceed {KEYWORD_CHARS} characters')
        values = value.split(',')
    elif isinstance(value, list):
        values = value
    else:
        raise ValueError('keywords must be a string or list of strings')
    if len(values) > KEYWORD_PHRASES:
        raise ValueError(f'at most {KEYWORD_PHRASES} keyword phrases')
    if any(not isinstance(item, str) for item in values):
        raise ValueError('keyword phrases must be strings')
    if any(len(item) > KEYWORD_PHRASE_CHARS for item in values):
        raise ValueError(f'keyword phrases exceed {KEYWORD_PHRASE_CHARS} characters')
    if sum(map(len, values)) + max(0, len(values) - 1) > KEYWORD_CHARS:
        raise ValueError(f'keywords exceed {KEYWORD_CHARS} characters')
    return [item.strip() for item in values if item.strip()]


def keyword_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError('keywords must be a string')
    keyword_list(value)
    return value


Keywords = Annotated[str, BeforeValidator(keyword_text)]
KeywordList = Annotated[list[str], BeforeValidator(keyword_list)]


class ScrapeInput(BaseModel):
    results_limit: LinkedinLimit = 100
    hours_old: Hours = 48
    distance: Distance = 10
    keywords: Keywords
    source: ScrapeSource = 'linkedin-apify'

    @model_validator(mode='after')
    def source_limit(self):
        if self.source == 'karriere-apify' and self.results_limit > 200:
            raise ValueError('karriere-apify results_limit must be at most 200')
        return self


class LinkedinScraperConfig(BaseModel):
    keywords: Keywords = ''
    results_limit: LinkedinLimit = 80
    hours_old: Hours = 24
    distance: Distance = 10


class KarriereScraperConfig(BaseModel):
    keywords: KeywordList = Field(default_factory=list)
    results_limit: KarriereLimit = 10
    hours_old: Hours | None = 24
    distance: Distance | None = 10


class LaneConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    name: ShortText = ''
    source: ScrapeSource = 'karriere-apify'
    keywords: KeywordList = Field(default_factory=list)
    results_limit: LinkedinLimit = 10
    hours_old: Hours = 24
    distance: Distance = 10

    @model_validator(mode='after')
    def source_limit(self):
        if self.source == 'karriere-apify' and self.results_limit > 200:
            raise ValueError('karriere-apify lane results_limit must be at most 200')
        return self


class DailyConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    enable_linkedin: bool = Field(default=False, strict=True)
    enable_karriere: bool = Field(default=False, strict=True)
    linkedin: LinkedinScraperConfig = Field(default_factory=lambda: LinkedinScraperConfig(results_limit=25))
    karriere: KarriereScraperConfig = Field(default_factory=KarriereScraperConfig)
    lanes: Annotated[list[LaneConfig], Field(max_length=MAX_LANES)] = Field(default_factory=list)


class AutoGenerateConfig(BaseModel):
    model_config = ConfigDict(extra='allow')
    min_rating: Literal['great', 'good', 'decent', 'stretch', 'poor'] = 'good'

    @model_validator(mode='before')
    @classmethod
    def migrate_rating_threshold(cls, value):
        if isinstance(value, dict):
            from job_policy import normalize_rating_config
            return normalize_rating_config({'auto_generate': value})['auto_generate']
        return value

    max_german_level: Annotated[str, Field(max_length=20)] = 'B1'
    tone: Instruction = ''
    document_engine: Literal['latex', 'typst'] = 'typst'
    typst_cv_template: Annotated[str, Field(max_length=200, pattern=r'^[\w-]+\.typ$')] = 'base-cv-moderner.typ'
    compact_cv: bool = False


class DocumentInstructions(BaseModel):
    model_config = ConfigDict(extra='allow')
    cv: Annotated[str, Field(max_length=4000)] = ''
    cover_letter: Annotated[str, Field(max_length=4000)] = ''


class CollectionConfig(BaseModel):
    """Validate recognized settings while preserving unrelated config extensions."""
    model_config = ConfigDict(extra='allow')
    openrouter_model: ModelName = ''
    document_model: ModelName = ''
    letter_verifier_model: ModelName | None = None
    sonar_model: ModelName = ''
    linkedin_location: ShortText = ''
    karriere_region: ShortText = ''
    linkedin: LinkedinScraperConfig = Field(default_factory=LinkedinScraperConfig)
    karriere: KarriereScraperConfig = Field(default_factory=KarriereScraperConfig)
    daily_scraper: DailyConfig = Field(default_factory=DailyConfig)
    auto_generate: AutoGenerateConfig = Field(default_factory=AutoGenerateConfig)
    document_instructions: DocumentInstructions = Field(default_factory=DocumentInstructions)


def validate_collection_config(config: dict) -> dict:
    # Only normalize fields actually present: missing defaults differ between UI and cron.
    return CollectionConfig.model_validate(config).model_dump(exclude_unset=True)


def validate_daily_overrides(linkedin_limit=None, karriere_limit=None, keywords=None, source_tag=None):
    from pydantic import TypeAdapter
    for value, contract in ((linkedin_limit, LinkedinLimit), (karriere_limit, KarriereLimit),
                            (keywords, Keywords), (source_tag, ShortText)):
        if value is not None:
            TypeAdapter(contract).validate_python(value)
