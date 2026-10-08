# Salvation relationships v1 audit

- Packet fingerprint: `54efe4941c8e01f3505bc8b4d7aa5db9b978cfef79adb8cc1928a0c0219fbccc`
- Leaf pack: `salvation-relationships-v1`
- Route policy: `salvation-route-supporting-mass-v1`
- Routed blocks: `126/518`
- Decision: `revise_four_relationship_boundaries`
- Ordinary reclassification activation: `false`

The reviewed `0.55` route remains a serviceable, recall-oriented provider-cost
gate. Three of the four threshold cases warrant the leaf pack. David P Ryder
video 4052 block 103 (`0.58`) is a genuine routing false positive: the target is
a Benjamin Franklin/George Whitefield anecdote about Philadelphia becoming more
religious, not a developed salvation relationship. Raising the threshold would
also discard useful `0.55` and `0.57` cases, so this isolated false positive is
recorded rather than used to move the boundary.

The leaf pack produces useful distinctions in strong cases, including atonement
and forgiveness in Ryder video 1200 block 35 and grace, forgiveness, repentance,
assurance, and cleansing in video 4458 block 70. Four question boundaries need
revision before activation:

1. `sanctification_transformation` overclaims repentance, surrender, healing,
   forgiveness, or narrative change as saving transformation. It must require an
   explicit relationship between saving work and holiness, deliverance from sin,
   or transformed life.
2. `justification_right_standing` overclaims forgiveness, grace, acceptance, or
   non-merit language as justification. It must require acquittal, credited or
   declared righteousness, or explicit right standing with God.
3. `divine_grace_initiative` can infer unearned grace from forgiveness alone. It
   must require grace, mercy, gift, divine initiative, or an explicit contrast
   with human earning.
4. `atonement_as_basis` underclaims direct sin-bearing language. Christ bearing
   the hearers' sins, guilt, or penalty is itself an asserted atoning relationship
   even when the target does not repeat the word salvation.

The other eight questions remain unchanged. V2 should rerun the same twelve
targets under a new leaf-pack cache identity, giving a paired comparison without
changing the router, sampler, broad topic evidence, or earlier caches.
