# TypeSafe Topic Behavior: sermon-topic-behavior-contract-v1

- Status: `passed`
- Model: `jev-1.13.0`
- Topic pack: `topics-v2-performed-worship-boundary`
- Cases: 21/21 passed
- Expectations: 41/41 passed
- Source provider requests: 4
- Input fingerprint: `969de41a17bdfb79f777804a692aa7d7710f0265dbfbdde1bf905f6f3891c170`

Confidence is shown as distribution concentration only. It is not used as a correctness score or pass threshold.

## PASS — Salvation absent from service administration

`salvation-absent-administration` · prominence_absent

Administrative logistics give salvation no meaningful attention.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `salvation_gospel` | 0.00–0.75 | 0.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | pass |

## PASS — Incidental salvation reference

`salvation-incidental-transition` · prominence_incidental

Salvation is named once but not developed; relationships organize the block.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `salvation_gospel` | 0.50–1.75 | 1.000 | 0.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.990 | pass |
| `relationships_family_interpersonal` | 2.50–4.00 | 3.030 | 0.000 | 0.210 | 0.030 | 0.270 | 0.490 | 0.200 | pass |

## PASS — Salvation supporting interpersonal forgiveness

`salvation-supports-forgiveness` · prominence_supporting

Saving grace is developed as the basis for a primarily relational application.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `salvation_gospel` | 1.50–2.75 | 2.180 | 0.000 | 0.090 | 0.700 | 0.160 | 0.050 | 0.700 | pass |
| `relationships_family_interpersonal` | 2.50–4.00 | 2.850 | 0.000 | 0.010 | 0.330 | 0.460 | 0.200 | 0.540 | pass |

## PASS — Salvation substantial alongside human need

`salvation-substantial-with-sin` · prominence_substantial

Sin and salvation are co-central rather than one being a passing support.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `salvation_gospel` | 2.50–4.00 | 3.950 | 0.000 | 0.000 | 0.000 | 0.040 | 0.960 | 0.960 | pass |
| `sin_fallenness_human_need` | 2.50–3.75 | 3.080 | 0.000 | 0.000 | 0.100 | 0.710 | 0.190 | 0.750 | pass |

## PASS — Salvation dominant through the block

`salvation-dominant-grace` · prominence_dominant

Every developed claim serves the saving work and reception of salvation.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `salvation_gospel` | 3.25–4.00 | 3.990 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | pass |

## PASS — Jesus and salvation overlap without competition

`overlap-jesus-salvation` · overlap_jesus_salvation

Christ's person and work and the salvation accomplished through that work are independently substantial.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `jesus_person_work` | 2.75–4.00 | 3.980 | 0.000 | 0.000 | 0.000 | 0.020 | 0.980 | 0.980 | pass |
| `salvation_gospel` | 2.50–4.00 | 3.810 | 0.000 | 0.020 | 0.010 | 0.090 | 0.880 | 0.840 | pass |

## PASS — Prophecy and Adventist doctrine overlap

`overlap-prophecy-adventist` · overlap_prophecy_adventist

Prophetic interpretation and explicitly Adventist sanctuary identity are both developed subjects.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `eschatology_prophecy` | 2.50–4.00 | 3.670 | 0.000 | 0.040 | 0.010 | 0.170 | 0.780 | 0.720 | pass |
| `adventist_doctrine_identity` | 2.50–4.00 | 3.810 | 0.000 | 0.020 | 0.010 | 0.100 | 0.870 | 0.840 | pass |

## PASS — Discipleship rather than developed sin

`boundary-sin-discipleship` · boundary_sin_discipleship

Temptation supplies the setting, while formation, practice, trust, and obedience are the developed topic.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `discipleship_spiritual_formation` | 2.75–4.00 | 3.990 | 0.000 | 0.000 | 0.000 | 0.010 | 0.990 | 0.990 | pass |
| `sin_fallenness_human_need` | 0.00–1.75 | 0.440 | 0.570 | 0.430 | 0.000 | 0.000 | 0.000 | 0.630 | pass |

## PASS — Compassionate service without evangelistic purpose

`boundary-mission-service` · boundary_mission_service

Direct aid and care are central; proclamation and disciple-making are expressly not the purpose.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `compassion_generosity_service` | 3.00–4.00 | 3.990 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.990 | pass |
| `mission_evangelism_witness` | 0.00–1.25 | 0.320 | 0.690 | 0.310 | 0.000 | 0.000 | 0.000 | 0.730 | pass |

## PASS — Personal ethics without public-life development

`boundary-ethics-public-life` · boundary_ethics_public_life

The block explicitly evaluates personal conduct but does not develop government, policy, or social structures.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `ethics_moral_conduct` | 3.00–4.00 | 3.990 | 0.000 | 0.000 | 0.000 | 0.010 | 0.990 | 0.990 | pass |
| `society_public_life` | 0.00–0.75 | 0.370 | 0.640 | 0.360 | 0.000 | 0.000 | 0.000 | 0.690 | pass |

## PASS — Human identity rather than creation as a subject

`boundary-human-nature-creation` · boundary_human_nature_creation

Creation language supports a sustained theological account of human identity and dignity.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `human_nature_identity` | 3.00–4.00 | 3.990 | 0.000 | 0.000 | 0.000 | 0.010 | 0.990 | 0.990 | pass |
| `creation_origins_created_order` | 0.50–2.00 | 1.160 | 0.120 | 0.690 | 0.120 | 0.050 | 0.020 | 0.660 | pass |

## PASS — Performed lyrics contain theology without discussing worship

`performed-lyrics-theological-subjects` · performed_lyrics

The lyrics genuinely contain Jesus, salvation, and divine-action topics, but performance alone does not make church or corporate worship the subject.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `jesus_person_work` | 2.00–4.00 | 3.510 | 0.000 | 0.070 | 0.040 | 0.180 | 0.710 | 0.590 | pass |
| `salvation_gospel` | 2.25–4.00 | 3.900 | 0.000 | 0.020 | 0.000 | 0.040 | 0.940 | 0.910 | pass |
| `god_character_action` | 1.50–3.50 | 3.270 | 0.000 | 0.100 | 0.070 | 0.290 | 0.540 | 0.390 | pass |
| `church_worship_community` | 0.00–1.25 | 0.040 | 0.970 | 0.030 | 0.000 | 0.000 | 0.000 | 0.970 | pass |

## PASS — Biblical quotation is not automatically the Scripture topic

`quotation-without-scripture-topic` · quotation

A quoted biblical sentence can develop salvation while leaving inspiration, authority, reliability, and interpretation undeveloped.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `salvation_gospel` | 2.00–4.00 | 3.870 | 0.000 | 0.030 | 0.000 | 0.030 | 0.940 | 0.890 | pass |
| `scripture_revelation` | 0.00–1.50 | 0.320 | 0.710 | 0.280 | 0.010 | 0.000 | 0.000 | 0.740 | pass |

## PASS — Negated public-life alternative

`negated-public-life` · negation

Political examples are explicitly rejected; personal spiritual formation is the developed subject.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `society_public_life` | 0.00–1.25 | 0.960 | 0.040 | 0.960 | 0.000 | 0.000 | 0.000 | 0.960 | pass |
| `discipleship_spiritual_formation` | 2.50–4.00 | 3.690 | 0.000 | 0.040 | 0.010 | 0.180 | 0.770 | 0.740 | pass |

## PASS — Mission appears only in leading context

`context-only-mission-mention` · context_only_mention

Leading context clarifies continuity but cannot independently establish mission in a target about prayer and trust.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `mission_evangelism_witness` | 0.00–0.75 | 0.030 | 0.980 | 0.020 | 0.000 | 0.000 | 0.000 | 0.980 | pass |
| `discipleship_spiritual_formation` | 2.50–4.00 | 3.970 | 0.000 | 0.000 | 0.000 | 0.030 | 0.970 | 0.970 | pass |

## PASS — Sparse caption retains raw topic meaning

`sparse-salvation-caption` · sparse_caption

The sparse target contains salvation language worth preserving as a raw observation, while deterministic projection policy—not confidence—decides whether it is attributable.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `salvation_gospel` | 1.00–3.50 | 2.180 | 0.000 | 0.600 | 0.000 | 0.040 | 0.360 | 0.020 | pass |

## PASS — Prodigal illustration serves a salvation point

`prodigal-illustration-salvation` · prodigal_illustration

A father-son narrative supplies relational material, but grace, reconciliation, adoption, and acceptance organize the point.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `salvation_gospel` | 2.75–4.00 | 3.990 | 0.000 | 0.000 | 0.000 | 0.010 | 0.990 | 0.990 | pass |
| `relationships_family_interpersonal` | 1.00–2.75 | 1.630 | 0.100 | 0.440 | 0.250 | 0.130 | 0.080 | 0.300 | pass |

## PASS — Closing sermon prayer after sparse caption fragments

`closing-prayer-after-sparse-gap` · closing_prayer_sparse_gap, sparse_caption

The prayer continues the sermon's salvation and formation themes; sparse separators are a boundary-policy issue, not grounds to erase raw topic meaning.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `discipleship_spiritual_formation` | 2.00–3.75 | 3.620 | 0.000 | 0.020 | 0.030 | 0.240 | 0.710 | 0.690 | pass |
| `salvation_gospel` | 1.50–3.50 | 2.390 | 0.010 | 0.350 | 0.150 | 0.230 | 0.260 | 0.000 | pass |

## PASS — Sustained spiritual conflict

`spiritual-conflict-positive` · spiritual_conflict_positive

Satan, demons, angels, and supernatural opposition are explicitly and repeatedly developed.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `spiritual_conflict_unseen_realm` | 3.25–4.00 | 3.980 | 0.000 | 0.000 | 0.000 | 0.010 | 0.990 | 0.990 | pass |

## PASS — Ordinary temptation without unseen agency

`spiritual-conflict-exclusion` · spiritual_conflict_exclusion

Temptation is ordinary habit resistance; no supernatural being, power, or warfare is developed.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `spiritual_conflict_unseen_realm` | 0.00–0.75 | 0.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | pass |
| `discipleship_spiritual_formation` | 2.25–4.00 | 3.670 | 0.010 | 0.030 | 0.030 | 0.140 | 0.790 | 0.730 | pass |

## PASS — Rejected daily-life alternative

`rejected-budgeting-alternative` · rejected_alternative

Budgeting and investment are rejected alternatives; guilt, grace, and forgiveness carry the positive claim.

| Topic | Expected | Score | P0 | P1 | P2 | P3 | P4 | Confidence | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `vocation_stewardship_daily_life` | 0.00–1.25 | 0.790 | 0.210 | 0.790 | 0.000 | 0.000 | 0.000 | 0.820 | pass |
| `salvation_gospel` | 2.75–4.00 | 3.880 | 0.000 | 0.010 | 0.010 | 0.070 | 0.910 | 0.900 | pass |
| `sin_fallenness_human_need` | 1.50–4.00 | 3.790 | 0.000 | 0.020 | 0.020 | 0.120 | 0.840 | 0.830 | pass |
