from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator

Variable = Literal['rain', 'temperature', 'wind_u', 'wind_v', 'pressure']

class SourceMetadata(BaseModel):
    source_id: str
    upstream_model_version: str
    initialization_time_utc: datetime
    provider_publication_time: datetime
    ingested_at: datetime
    valid_start_time: datetime
    valid_end_time: datetime
    lead_time: int = Field(ge=0, le=384)
    variable: Variable
    units: str
    vertical_level_or_height: str
    ensemble_member: str = 'deterministic'
    grid_id: str
    quality_flags: list[str] = Field(default_factory=list)
    file_checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    licence_reference: str
    data_kind: Literal['forecast', 'synthetic']

    @model_validator(mode='after')
    def check_times(self):
        for t in [self.initialization_time_utc,self.provider_publication_time,self.ingested_at,self.valid_start_time,self.valid_end_time]:
            if t.tzinfo is None or t.utcoffset().total_seconds() != 0:
                raise ValueError('All timestamps must be timezone-aware UTC')
        if self.valid_end_time < self.valid_start_time:
            raise ValueError('Invalid accumulation window')
        if (self.valid_end_time-self.initialization_time_utc).total_seconds() != self.lead_time*3600:
            raise ValueError('Lead time and valid time disagree')
        if self.variable=='rain' and self.valid_start_time==self.valid_end_time:
            raise ValueError('Rainfall requires an accumulation window')
        if self.provider_publication_time > self.ingested_at:
            raise ValueError('Input cannot be ingested before publication')
        return self

class ReviewInput(BaseModel):
    run_id: str = Field(min_length=1,max_length=100)
    text: str = Field(min_length=5,max_length=4000)
    status: Literal['draft','reviewed','approved'] = 'draft'
    lat: float = Field(ge=5,le=38)
    lng: float = Field(ge=65,le=100)

class ReplayInput(BaseModel):
    run_id: str
    as_of: datetime

class PromotionInput(BaseModel):
    version: str
    reason: str = Field(min_length=10,max_length=1000)
