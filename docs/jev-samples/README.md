# Jev request/response samples

Hand-sent requests to the TypeSafe-compatible endpoint of Vercel AI Gateway
(`POST https://ai-gateway.vercel.sh/typesafe/v1/systemone`, model `typesafe-ai/jev`),
kept so the exact wire format is visible without running the CLI.
Files come in pairs: `NN-name.request.json` is what was sent (the
`Authorization` header is not part of the body and is not recorded),
`NN-name.response.json` is the verbatim reply.

| File | What it shows |
| --- | --- |
| `00-invalid-score-criteria.error.json` | Error shape. A `score` question was sent with `criteria` as an object; the API requires an ordered array. |
| `01-three-primitives.*` | One request carrying a `choice`, a `score` and a `noul` question about the same loop (`count_quotes` from the toy crate). Choice returns `choice` + `probabilities` + `confidence`; score returns a probability-weighted `score` plus `legend`; noul returns a single probability. |

Field notes:

- `choice.criteria` is an object (`option name -> description`). `score.criteria` is an array (ordered level descriptions). `noul` takes only `instructions`.
- Questions in one request are evaluated independently and in parallel; a later question cannot depend on an earlier answer within the same request.
- `provider_metadata.gateway.cost` is the amount billed (0 on the free tier); `marketCost` is the list price.
- The CLI writes every real request/response as JSONL under `artifacts/jev-log/<target>/` (git-ignored); these samples are the only ones tracked.
