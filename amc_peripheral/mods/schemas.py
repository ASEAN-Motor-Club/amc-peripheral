"""Pydantic schemas for tire mod build API."""

from enum import Enum

from pydantic import BaseModel, Field


class VehicleType(str, Enum):
    Small = "Small"
    Medium = "Medium"
    Large = "Large"
    HeavyMachine = "HeavyMachine"
    MotorCycle = "MotorCycle"


class TirePhysicsSchema(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_]+$", min_length=3, max_length=50)
    template: str = "BasicTire_45"
    static_mu: float = Field(ge=0.5, le=3.0)
    sliding_mu: float = Field(ge=0.3, le=3.0)
    offroad_friction: float | None = Field(default=None, ge=0.5, le=3.0)


class TirePartSchema(BaseModel):
    row_name: str = Field(pattern=r"^[A-Za-z0-9_]+$", min_length=2, max_length=50)
    display_name: list[str] = Field(min_length=1, max_length=3)
    cost: int = Field(ge=100, le=50000)
    mass_kg: int = Field(ge=5, le=50)
    vehicle_types: list[VehicleType] = Field(min_length=1)
    tire_asset_path: str


class TireEntrySchema(BaseModel):
    tire_physics: TirePhysicsSchema
    tire_part: TirePartSchema


class BuildRequest(BaseModel):
    pack_name: str = Field(
        pattern=r"^[A-Za-z0-9_]+$", min_length=3, max_length=50
    )
    tires: list[TireEntrySchema] = Field(min_length=1, max_length=10)
    compat_mods: list[str] = Field(default=[], max_length=5)


class ModInspection(BaseModel):
    mod_id: str
    filename: str
    file_count: int
    has_vehicle_parts0: bool
    tire_asset_count: int
