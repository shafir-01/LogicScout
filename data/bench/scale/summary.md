# LogicScout bench summary

## Per-arm

| world | arm | runs (ok) | systems | held-out cases n | successes | rate | 95% Wilson CI | probes (mean) | pred acc / persistence | model calls | tokens | tokens per success |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| forge | idle | 100 (100) | 100 | 600 | 0 | 0.00 | [0.00, 0.01] | 0 | - / - | 0 | 0 | 0 |
| forge | no_model | 100 (100) | 100 | 600 | 123 | 0.20 | [0.17, 0.24] | 81 | 0.94 / 0.66 | 0 | 0 | 0 |
| forge | random | 100 (100) | 100 | 600 | 16 | 0.03 | [0.02, 0.04] | 0 | - / - | 0 | 0 | 0 |
| forge | tabular | 100 (100) | 100 | 600 | 0 | 0.00 | [0.00, 0.01] | 120 | 0.80 / 0.66 | 0 | 0 | 0 |
| relay | idle | 8 (8) | 1 | 32 | 0 | 0.00 | [0.00, 0.11] | 0 | - / - | 0 | 0 | 0 |
| relay | no_model | 8 (8) | 1 | 32 | 4 | 0.12 | [0.05, 0.28] | 98 | 0.88 / 0.76 | 0 | 0 | 0 |
| relay | random | 8 (8) | 1 | 32 | 0 | 0.00 | [0.00, 0.11] | 0 | - / - | 0 | 0 | 0 |
| relay | tabular | 8 (8) | 1 | 32 | 0 | 0.00 | [0.00, 0.11] | 100 | 0.80 / 0.76 | 0 | 0 | 0 |

## Hidden change

| world | arm | runs | change applied | false alarms before change (runs with any) | control steps before change | detected (95% CI) | detection delay, steps (median; all) | recovered (95% CI) | recovery time, steps (median) |
|---|---|---|---|---|---|---|---|---|---|
| forge | no_model | 100 | 100 | 28 (24) | 4000 | 19/100 [0.13, 0.28] | 31.0; [1, 2, 3, 5, 7, 10, 27, 27, 29, 31, 35, 40, 49, 55, 70, 91, 98, 106, 196] | 9/100 [0.05, 0.16] | 53.0 |
| relay | no_model | 8 | 8 | 5 (2) | 320 | 7/8 [0.53, 0.98] | 8.0; [2, 5, 5, 8, 9, 131, 162] | 2/8 [0.07, 0.59] | 22.0 |

## Per-seed rows

| world | system | arm | seed | status | successes / n | probes | model calls | tokens | playbook | detected / delay / recovered |
|---|---|---|---|---|---|---|---|---|---|---|
| forge | g101 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g101 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g101 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g101 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g102 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g102 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g102 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g102 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g103 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g103 | no_model | 0 | ok | 2 / 6 | 86 | 0 | 0 | planner | yes / 10 / yes |
| forge | g103 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g103 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g104 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g104 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g104 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g104 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g105 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g105 | no_model | 0 | ok | 6 / 6 | 96 | 0 | 0 | planner | no / - / yes |
| forge | g105 | random | 0 | ok | 2 / 6 | 0 | 0 | 0 | - | - |
| forge | g105 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g106 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g106 | no_model | 0 | ok | 0 / 6 | 108 | 0 | 0 | planner | no / - / no |
| forge | g106 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g106 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g107 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g107 | no_model | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | yes / 7 / no |
| forge | g107 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g107 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g108 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g108 | no_model | 0 | ok | 2 / 6 | 92 | 0 | 0 | planner | no / - / no |
| forge | g108 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g108 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g109 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g109 | no_model | 0 | ok | 0 / 6 | 61 | 0 | 0 | planner | no / - / no |
| forge | g109 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g109 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g110 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g110 | no_model | 0 | ok | 0 / 6 | 60 | 0 | 0 | planner | no / - / no |
| forge | g110 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g110 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g111 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g111 | no_model | 0 | ok | 0 / 6 | 65 | 0 | 0 | planner | no / - / no |
| forge | g111 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g111 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g112 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g112 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g112 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g112 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g113 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g113 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g113 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g113 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g114 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g114 | no_model | 0 | ok | 0 / 6 | 61 | 0 | 0 | planner | no / - / no |
| forge | g114 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g114 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g115 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g115 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g115 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g115 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g116 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g116 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g116 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g116 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g117 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g117 | no_model | 0 | ok | 6 / 6 | 61 | 0 | 0 | planner | no / - / no |
| forge | g117 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g117 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g118 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g118 | no_model | 0 | ok | 0 / 6 | 61 | 0 | 0 | planner | no / - / no |
| forge | g118 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g118 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g119 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g119 | no_model | 0 | ok | 6 / 6 | 42 | 0 | 0 | planner | no / - / no |
| forge | g119 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g119 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g120 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g120 | no_model | 0 | ok | 0 / 6 | 83 | 0 | 0 | planner | yes / 5 / no |
| forge | g120 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g120 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g121 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g121 | no_model | 0 | ok | 0 / 6 | 67 | 0 | 0 | planner | no / - / no |
| forge | g121 | random | 0 | ok | 1 / 6 | 0 | 0 | 0 | - | - |
| forge | g121 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g122 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g122 | no_model | 0 | ok | 6 / 6 | 89 | 0 | 0 | planner | yes / 1 / yes |
| forge | g122 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g122 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g123 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g123 | no_model | 0 | ok | 6 / 6 | 67 | 0 | 0 | planner | no / - / no |
| forge | g123 | random | 0 | ok | 1 / 6 | 0 | 0 | 0 | - | - |
| forge | g123 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g124 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g124 | no_model | 0 | ok | 6 / 6 | 66 | 0 | 0 | planner | no / - / no |
| forge | g124 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g124 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g125 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g125 | no_model | 0 | ok | 6 / 6 | 101 | 0 | 0 | planner | yes / 40 / yes |
| forge | g125 | random | 0 | ok | 1 / 6 | 0 | 0 | 0 | - | - |
| forge | g125 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g126 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g126 | no_model | 0 | ok | 2 / 6 | 89 | 0 | 0 | planner | no / - / no |
| forge | g126 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g126 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g127 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g127 | no_model | 0 | ok | 0 / 6 | 61 | 0 | 0 | planner | no / - / no |
| forge | g127 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g127 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g128 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g128 | no_model | 0 | ok | 6 / 6 | 79 | 0 | 0 | planner | no / - / no |
| forge | g128 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g128 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g129 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g129 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g129 | random | 0 | ok | 1 / 6 | 0 | 0 | 0 | - | - |
| forge | g129 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g130 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g130 | no_model | 0 | ok | 0 / 6 | 114 | 0 | 0 | planner | yes / 70 / no |
| forge | g130 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g130 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g131 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g131 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g131 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g131 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g132 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g132 | no_model | 0 | ok | 5 / 6 | 105 | 0 | 0 | planner | yes / 49 / yes |
| forge | g132 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g132 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g133 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g133 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g133 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g133 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g134 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g134 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g134 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g134 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g135 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g135 | no_model | 0 | ok | 0 / 6 | 108 | 0 | 0 | planner | no / - / no |
| forge | g135 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g135 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g136 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g136 | no_model | 0 | ok | 6 / 6 | 60 | 0 | 0 | planner | no / - / no |
| forge | g136 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g136 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g137 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g137 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g137 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g137 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g138 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g138 | no_model | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | yes / 55 / no |
| forge | g138 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g138 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g139 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g139 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g139 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g139 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g140 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g140 | no_model | 0 | ok | 0 / 6 | 91 | 0 | 0 | planner | yes / 98 / no |
| forge | g140 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g140 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g141 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g141 | no_model | 0 | ok | 0 / 6 | 61 | 0 | 0 | planner | no / - / no |
| forge | g141 | random | 0 | ok | 1 / 6 | 0 | 0 | 0 | - | - |
| forge | g141 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g142 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g142 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g142 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g142 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g143 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g143 | no_model | 0 | ok | 0 / 6 | 60 | 0 | 0 | planner | no / - / no |
| forge | g143 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g143 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g144 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g144 | no_model | 0 | ok | 6 / 6 | 102 | 0 | 0 | planner | no / - / yes |
| forge | g144 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g144 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g145 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g145 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g145 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g145 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g146 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g146 | no_model | 0 | ok | 0 / 6 | 72 | 0 | 0 | planner | no / - / no |
| forge | g146 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g146 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g147 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g147 | no_model | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | yes / 3 / no |
| forge | g147 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g147 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g148 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g148 | no_model | 0 | ok | 6 / 6 | 47 | 0 | 0 | planner | no / - / no |
| forge | g148 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g148 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g149 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g149 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g149 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g149 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g150 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g150 | no_model | 0 | ok | 0 / 6 | 67 | 0 | 0 | planner | no / - / no |
| forge | g150 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g150 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g151 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g151 | no_model | 0 | ok | 0 / 6 | 118 | 0 | 0 | planner | yes / 2 / no |
| forge | g151 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g151 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g152 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g152 | no_model | 0 | ok | 6 / 6 | 45 | 0 | 0 | planner | no / - / no |
| forge | g152 | random | 0 | ok | 1 / 6 | 0 | 0 | 0 | - | - |
| forge | g152 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g153 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g153 | no_model | 0 | ok | 0 / 6 | 60 | 0 | 0 | planner | no / - / no |
| forge | g153 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g153 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g154 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g154 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g154 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g154 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g155 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g155 | no_model | 0 | ok | 0 / 6 | 63 | 0 | 0 | planner | no / - / no |
| forge | g155 | random | 0 | ok | 4 / 6 | 0 | 0 | 0 | - | - |
| forge | g155 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g156 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g156 | no_model | 0 | ok | 0 / 6 | 75 | 0 | 0 | planner | no / - / no |
| forge | g156 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g156 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g157 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g157 | no_model | 0 | ok | 6 / 6 | 120 | 0 | 0 | planner | yes / 35 / yes |
| forge | g157 | random | 0 | ok | 1 / 6 | 0 | 0 | 0 | - | - |
| forge | g157 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g158 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g158 | no_model | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | yes / 29 / no |
| forge | g158 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g158 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g159 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g159 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g159 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g159 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g160 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g160 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g160 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g160 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g161 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g161 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g161 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g161 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g162 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g162 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g162 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g162 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g163 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g163 | no_model | 0 | ok | 2 / 6 | 62 | 0 | 0 | planner | no / - / no |
| forge | g163 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g163 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g164 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g164 | no_model | 0 | ok | 2 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g164 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g164 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g165 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g165 | no_model | 0 | ok | 6 / 6 | 94 | 0 | 0 | planner | yes / 106 / no |
| forge | g165 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g165 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g166 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g166 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g166 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g166 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g167 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g167 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g167 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g167 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g168 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g168 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g168 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g168 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g169 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g169 | no_model | 0 | ok | 0 / 6 | 108 | 0 | 0 | planner | no / - / no |
| forge | g169 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g169 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g170 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g170 | no_model | 0 | ok | 0 / 6 | 67 | 0 | 0 | planner | no / - / no |
| forge | g170 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g170 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g171 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g171 | no_model | 0 | ok | 2 / 6 | 108 | 0 | 0 | planner | yes / 27 / yes |
| forge | g171 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g171 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g172 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g172 | no_model | 0 | ok | 0 / 6 | 62 | 0 | 0 | planner | no / - / no |
| forge | g172 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g172 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g173 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g173 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g173 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g173 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g174 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g174 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g174 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g174 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g175 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g175 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g175 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g175 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g176 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g176 | no_model | 0 | ok | 0 / 6 | 74 | 0 | 0 | planner | no / - / no |
| forge | g176 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g176 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g177 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g177 | no_model | 0 | ok | 0 / 6 | 61 | 0 | 0 | planner | no / - / no |
| forge | g177 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g177 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g178 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g178 | no_model | 0 | ok | 0 / 6 | 108 | 0 | 0 | planner | yes / 31 / no |
| forge | g178 | random | 0 | ok | 2 / 6 | 0 | 0 | 0 | - | - |
| forge | g178 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g179 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g179 | no_model | 0 | ok | 0 / 6 | 102 | 0 | 0 | planner | no / - / no |
| forge | g179 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g179 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g180 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g180 | no_model | 0 | ok | 2 / 6 | 97 | 0 | 0 | planner | no / - / no |
| forge | g180 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g180 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g181 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g181 | no_model | 0 | ok | 6 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g181 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g181 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g182 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g182 | no_model | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | no / - / no |
| forge | g182 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g182 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g183 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g183 | no_model | 0 | ok | 0 / 6 | 75 | 0 | 0 | planner | no / - / no |
| forge | g183 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g183 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g184 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g184 | no_model | 0 | ok | 0 / 6 | 62 | 0 | 0 | planner | no / - / no |
| forge | g184 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g184 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g185 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g185 | no_model | 0 | ok | 0 / 6 | 61 | 0 | 0 | planner | no / - / no |
| forge | g185 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g185 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g186 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g186 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g186 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g186 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g187 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g187 | no_model | 0 | ok | 0 / 6 | 70 | 0 | 0 | planner | no / - / no |
| forge | g187 | random | 0 | ok | 1 / 6 | 0 | 0 | 0 | - | - |
| forge | g187 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g188 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g188 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g188 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g188 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g189 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g189 | no_model | 0 | ok | 0 / 6 | 105 | 0 | 0 | planner | yes / 27 / no |
| forge | g189 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g189 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g190 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g190 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g190 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g190 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g191 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g191 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g191 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g191 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g192 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g192 | no_model | 0 | ok | 2 / 6 | 120 | 0 | 0 | planner | yes / 91 / yes |
| forge | g192 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g192 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g193 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g193 | no_model | 0 | ok | 6 / 6 | 45 | 0 | 0 | planner | no / - / no |
| forge | g193 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g193 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g194 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g194 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g194 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g194 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g195 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g195 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g195 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g195 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g196 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g196 | no_model | 0 | ok | 6 / 6 | 54 | 0 | 0 | planner | no / - / no |
| forge | g196 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g196 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g197 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g197 | no_model | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | yes / 196 / no |
| forge | g197 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g197 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g198 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g198 | no_model | 0 | ok | 0 / 6 | 94 | 0 | 0 | planner | no / - / no |
| forge | g198 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g198 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g199 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g199 | no_model | 0 | ok | 0 / 6 | 60 | 0 | 0 | planner | no / - / no |
| forge | g199 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g199 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| forge | g200 | idle | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g200 | no_model | 0 | ok | 0 / 6 | 78 | 0 | 0 | planner | no / - / no |
| forge | g200 | random | 0 | ok | 0 / 6 | 0 | 0 | 0 | - | - |
| forge | g200 | tabular | 0 | ok | 0 / 6 | 120 | 0 | 0 | planner | - |
| relay | standard | idle | 0 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | idle | 1 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | idle | 2 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | idle | 3 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | idle | 4 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | idle | 5 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | idle | 6 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | idle | 7 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | no_model | 0 | ok | 0 / 4 | 100 | 0 | 0 | planner | yes / 2 / no |
| relay | standard | no_model | 1 | ok | 1 / 4 | 100 | 0 | 0 | planner | yes / 162 / no |
| relay | standard | no_model | 2 | ok | 0 / 4 | 100 | 0 | 0 | planner | no / - / no |
| relay | standard | no_model | 3 | ok | 1 / 4 | 100 | 0 | 0 | planner | yes / 5 / yes |
| relay | standard | no_model | 4 | ok | 0 / 4 | 100 | 0 | 0 | planner | yes / 9 / no |
| relay | standard | no_model | 5 | ok | 1 / 4 | 100 | 0 | 0 | planner | yes / 5 / no |
| relay | standard | no_model | 6 | ok | 1 / 4 | 81 | 0 | 0 | planner | yes / 8 / yes |
| relay | standard | no_model | 7 | ok | 0 / 4 | 100 | 0 | 0 | planner | yes / 131 / no |
| relay | standard | random | 0 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | random | 1 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | random | 2 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | random | 3 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | random | 4 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | random | 5 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | random | 6 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | random | 7 | ok | 0 / 4 | 0 | 0 | 0 | - | - |
| relay | standard | tabular | 0 | ok | 0 / 4 | 100 | 0 | 0 | planner | - |
| relay | standard | tabular | 1 | ok | 0 / 4 | 100 | 0 | 0 | planner | - |
| relay | standard | tabular | 2 | ok | 0 / 4 | 100 | 0 | 0 | planner | - |
| relay | standard | tabular | 3 | ok | 0 / 4 | 100 | 0 | 0 | planner | - |
| relay | standard | tabular | 4 | ok | 0 / 4 | 100 | 0 | 0 | planner | - |
| relay | standard | tabular | 5 | ok | 0 / 4 | 100 | 0 | 0 | planner | - |
| relay | standard | tabular | 6 | ok | 0 / 4 | 100 | 0 | 0 | planner | - |
| relay | standard | tabular | 7 | ok | 0 / 4 | 100 | 0 | 0 | planner | - |
