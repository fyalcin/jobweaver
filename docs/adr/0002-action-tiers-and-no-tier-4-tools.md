# Actions are split into tiers, and Tier 4 tools do not exist

Tier 1 reading and Tier 2 cheap undoable changes are free. Tier 3 (scraping, model scoring, generation) is capped per day inside the server; scoring and generation run autonomously, scraping needs the client's approval each time. Tier 4 (deleting jobs, changing settings, editing personal CV sources, direct database access, sending applications) is not exposed at all, so a confused or prompt-injected agent cannot do it. Scraped job text is untrusted and is marked so. Sending applications stays manual.
