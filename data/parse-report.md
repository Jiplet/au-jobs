# Parse report

Total ANZSCO 4-digit unit groups (from the ABS ANZSCO 2022 structure file): 364

## Coverage per layer

| Layer | Matched | Notes |
|---|---|---|
| Employment (February 2026) | 346/364 (95%) | Australia total, persons, summed from Male+Female across all 8 states/territories - the source file has no pre-aggregated total. |
| Average weekly earnings | 342/364 (94%) | This is a MEAN, not a median - ABS does not publish a median at unit group level. Many small occupations are suppressed by ABS (too few survey respondents) and are correctly blank, not zero. |
| Projected employment growth | 346/364 (95%) | 5-year (to May 2030) and 10-year (to May 2035), JSA Employment Projections. |
| Skills shortage rating | 311/364 (85%) | National rating, JSA Occupation Shortage List cycle 2025, pre-aggregated to unit group by JSA. |
| Task descriptions | 0/364 (0%) | Not available as a bulk file from either ABS or JSA (ABS only publishes lead statements as ~360 individual HTML pages, one per unit group). score.py asks the LLM to infer likely tasks from the title and major group before scoring - see prompts/ai-exposure.md. This is a real gap, documented rather than papered over. |

## What this means for the map

Every occupation has a code, title, and major group. Employment coverage should be at or near 100% since it comes from the same classification vintage as the structure file. Earnings, growth, and shortage will each have some gaps: earnings from ABS suppression of small occupations, growth and shortage from vintage mismatches between JSA's occupation list and the ABS 2022 structure. The site's legend marks a layer 'not available for this occupation' rather than plotting a zero or a made-up value.
