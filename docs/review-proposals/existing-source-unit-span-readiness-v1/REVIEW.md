# Existing source-unit range check

**Stop before inference. The existing normalized source units are too coarse for the proposed target-selection interface.** This provider-free check preserved all minute windows and source coordinates, and prepared no model questions, runtime or execution packet.

[Generated inventory and geometry report](/Users/briancummings/Documents/PastorSearchData/evaluation/existing-source-unit-span-readiness-v1/3d6645132f01a80e11f47afbe2cf15cd33655f4d45ccc7a2c0485731fb6cad37/readiness-v1.json) contains all 17 selected contexts' complete source units and excluded partial edge units, plus diagnostic minimum whole-unit covers for the 12 earlier adequate references. References are used only to check representation, not to construct discovery candidates or rescue targets.

## Findings

All 12 frozen focal geometries require boundaries inside existing units. **Zero are exactly expressible as whole-unit ranges.** Extra text alone is not proof of semantic incompatibility; the following source-reviewed failures are the substantive blockers.

| G2 example | Whole-unit result |
|---|---|
| CE-01: Colossians rule → govern/control | Separate units `520:F0030/F0031`, but the anchor unit already combines quotation and preacher explanation. Distinct unit IDs do not establish clean semantic roles. |
| CE-02: labor pains → known nearness, unknown day/hour | Both roles occupy `951:F0074`. Every whole-unit cover of either role necessarily overlaps the other; distinct nonoverlapping targets are impossible. |
| CE-03: taken/left → destruction | Separate units `951:F0081/F0086`; both add other quotations, discourse or role content. Geometric separation is possible, semantic target compatibility is not established. |
| CE-04: not-his → do-not-belong | Both roles occupy `1094:F0075`; whole-unit ranges cannot separate them. |

The eight G3 focal targets also sit inside larger units:

| Case | Unit | Target-boundary issue |
|---|---|---|
| CE-05 | `951:F0109` | Several independent present-listener warnings/instructions and surrounding Bible discussion. |
| CE-06 | `1094:F0082` | Closest case: the complete conditional prayer/protection act plus preceding “You can't do it.” Semantic acceptability of that broader target remains unestablished; no automatic rejection solely for extra words. |
| CE-07 | `951:F0098` | Historical/model speech and present preacher exhortation share the unit. |
| CE-08 | `520:F0021` | Paul/verse discussion and the present turn-to-Colossians instruction share the unit. |
| CE-09 | `951:F0032` | Distinct reported warnings, hypothetical/model speech and preacher application share the unit. |
| CE-10 | `951:F0038` | Moses's request and multiple divine replies share the unit. |
| CE-11 | `951:F0014` | Matt's request, preacher narration and other modeled/current speech share the unit. |
| CE-12 | `520:F0028` | Reported put-on-love exhortation shares a unit with other verse/explanation content. |

A contiguous range of multiple whole units can only add text; it cannot remove an unwanted prefix, another speaker or an independently sufficient neighboring act inside one unit. Labeling these paragraphs with IDs would remove numeric-offset arithmetic but leave the substantive target-granularity problem. Reference support remaining available in the envelope does not make the whole paragraph a valid utterance or directed role.

This is a development representation diagnostic, not a proof that every possible observation in these contexts is inaccessible. No complete opportunity census or recall score was computed. Some broader targets could be source-compatible; the two definite G2 collisions already show that the proposed unit inventory cannot support the required distinctions generally. The historical clipped/control slate is not rescored.

## Implementation and limits

The check inventories existing units before consulting reference spans. It copies canonical text exactly, preserves IDs/coordinates/newlines and excludes edge units that extend beyond the selected context. It never clips a unit into a new semantic target, expands an envelope, enumerates pair candidates, changes segmentation or assigns source voice/recipient/adoption.

**50 focused tests passed**, including the two-roles-in-one-unit impossibility, separate exact units, edge clipping refusal, canonical substring copying, foreign-source rejection and CLI isolation. All generated artifacts remain under the configured application base directory. No provider requests, model loading, semantic/admission execution, source/reference changes, threshold changes, collection or projection occurred.

Reproduce this small provider-free check:

```bash
pte analysis structure-readiness --unit-span-check --json
```

**Recommendation:** do not prepare a paid whole-unit selection test. If span nomination is pursued, its next prerequisite is a finer target-only representation *inside the unchanged minute windows*, preserving canonical coordinates and qualifiers. That would be a separate prospective representation decision; this check does not implement it, reopen the retired collector, or authorize inference. Existing units remain useful for source lineage and context transport, but cannot be assumed to be atomic semantic targets.
