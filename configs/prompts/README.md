# Prompt versions

Versioned prompt files live here (`extraction_v1.md`, `adjudication_v1.md`, ...). Each claim's
`extracted_by.prompt_version` field points at a filename in this directory, so any extraction
regression can be bisected to the exact prompt that produced it.

Populated starting Week 2 (extraction swarm). Empty in the Week 1 skeleton.
