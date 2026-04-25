.provider_schemas[$p].resource_schemas
| keys[]
| select(contains($f))
