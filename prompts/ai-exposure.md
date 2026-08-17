# Rubric: digital AI exposure

This is the prompt score.py sends to the model, one batch of occupations at a time. It is
the only thing that decides the colour you see when you toggle "AI exposure" on the map.
Swap this file for a different question (humanoid robotics, offshoring, climate transition,
regulation) and rerun `uv run python score.py` to recolour the whole map with something
else entirely.

## The question

For each occupation, estimate how much CURRENT, mostly-digital AI (large language models,
coding assistants, image/video generation, agentic tools that plan and act, and similar
systems that exist and are in real use in 2026) is likely to change the day-to-day TASKS of
that occupation over the next few years.

This is a question about task exposure, not about job loss, headcount, or wages. Score how
much of what someone in this job actually does, hour to hour, is the kind of work these
tools are already good at or are clearly heading towards: drafting, summarising,
classifying, coding, image/video generation, structured data work, first-pass analysis,
routine correspondence, scheduling, and similar. A high score does not mean "this job will
disappear." It means "a lot of the substance of this job is the kind of work AI tools can
now do a meaningful share of."

## Scale: 0 to 10

- **0 to 1**: Almost entirely physical, situational, or interpersonal work that current AI
  cannot meaningfully touch. The job is built around being physically present, handling
  physical materials, or in-person judgement calls in unpredictable environments.
  Example anchor: Concreters, Firefighters, Aged and Disabled Carers.
- **2 to 3**: Mostly physical or in-person work with a minority of desk-based, information
  tasks (rostering, reporting, ordering supplies) that AI tools can already assist with.
  Example anchor: Electricians, Registered Nurses, Retail Managers.
- **4 to 5**: A real mix. Meaningful chunks of the role are information work (assessment,
  documentation, correspondence, planning) alongside chunks that need a human physically
  present, legally accountable, or making a judgement call with real stakes.
  Example anchor: General Practitioners, Primary School Teachers, Quantity Surveyors.
- **6 to 7**: Mostly desk-based, information-processing work. A large share of daily tasks
  (drafting, analysing, coding, designing, researching) overlaps with what current AI tools
  do well, though human judgement, accountability, or client relationships still anchor the
  role.
  Example anchor: Accountants, Marketing Specialists, Solicitors.
- **8 to 10**: The core output of the job is digital content, code, analysis, or structured
  information, produced largely at a desk, where AI tools can already do a first-pass
  version of a large share of the work.
  Example anchor: Software and Applications Programmers, Copywriters, Data Analysts,
  Graphic Designers.

Use the whole scale. Do not cluster everything in the middle.

## What this is NOT measuring, and must not be conflated with

- **Not a job loss or unemployment forecast.** A high score does not mean the job goes away.
  Software developers, for instance, should score high on task exposure while demand for
  the role may grow, shrink, or hold steady: none of that is being asked here.
- **Not demand elasticity.** Whether more or less of this work gets done in total, whether
  cheaper delivery increases demand (induced demand), and whether headcount rises or falls
  are all separate questions this score does not answer.
- **Not regulation or credentialing.** Whether a licence, union agreement, safety
  regulation, or professional body currently requires a human to do the work is not part of
  this score, even where that barrier is real and durable.
- **Not a preference for human contact.** Whether customers or patients want a human
  regardless of technical capability (a GP consultation, a funeral director, a hairdresser)
  is not part of this score.
- **Not about which tasks get literally 100% automated.** Almost no occupation gets
  fully replaced task-by-task; score the overall shift in what a typical week looks like,
  not an all-or-nothing automation switch.

## Input you get per occupation

Title, ANZSCO 4-digit code, major group, and (where the source data has it) a short list of
typical tasks. Bulk task-level descriptions are not available from ABS or JSA for every
occupation (see data/parse-report.md), so where tasks_text is empty you are asked to infer,
briefly, what someone in this job most likely does day to day given the title and major
group, before scoring. This makes titles-only occupations a slightly weaker input than ones
with real task text: the model is doing two steps (infer, then score) instead of one.

## Output format

Respond with ONLY a JSON array, no prose before or after, no markdown code fence. One object
per occupation, in the same order you were given them:

```json
[
  {"code": 2613, "score": 8, "rationale": "One sentence, concrete, references actual tasks."},
  {"code": 3611, "score": 2, "rationale": "One sentence, concrete, references actual tasks."}
]
```

`code` must be the exact ANZSCO 4-digit code you were given, `score` an integer 0 to 10,
`rationale` one plain sentence (not a list, no hedging preamble like "This occupation...").
