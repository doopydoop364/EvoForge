from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["evolution", "ppo", "hybrid"] = "hybrid"
    game: str = "snake"
    population: int = Field(24, ge=2, le=4096)
    generations: int = Field(20, ge=1, le=1000000)
    elites: int = Field(2, ge=1, le=4095)
    ppo_candidates: int = Field(3, ge=0, le=4096)
    ppo_episodes: int = Field(4, ge=1, le=10000)
    eval_episodes: int = Field(3, ge=1, le=10000)
    size: int = Field(10, ge=5, le=128)
    max_steps: int = Field(300, ge=1, le=100000)
    seed: int = Field(42, ge=0, le=2147483647)
    hidden: int | list[int] = 64
    mutation_probability: float = Field(0.05, ge=0, le=1)
    mutation_sigma: float = Field(0.08, ge=0, allow_inf_nan=False)
    game_config: dict[str, Any] = Field(default_factory=dict)
    environment_step_budget: int | None = Field(None, ge=1)


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    config: TrainingConfig = Field(default_factory=TrainingConfig)


class Worker(BaseModel):
    experiment: str
    identity: str
    pid: int | None = None
    incarnation: str | None = None
    heartbeat: float
    request: str | None = None
    error: str | None = None
    generation: int


class Experiment(BaseModel):
    id: str
    config: dict[str, Any]
    status: str
    created: float
    updated: float
    game_version: str
    algorithm_version: int
    archived: int
    worker: Worker | None


class Game(BaseModel):
    id: str
    name: str
    version: str
    observation_size: int
    action_size: int
    score_name: str


class NamedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
