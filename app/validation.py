from typing import Annotated

from pydantic import StringConstraints

# A required string that must not be empty or whitespace-only. Strips
# surrounding whitespace on validation (matching the frontend's .trim()
# before submit) so "  " and "" are both rejected the same way.
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
