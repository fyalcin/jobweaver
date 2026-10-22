"""List-compatible acquisition result with explicit partial/failure evidence."""
class SourceJobs(list):
    def __init__(self, jobs=(), errors=()):
        super().__init__(jobs)
        self.errors = list(errors)
