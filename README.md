# Sharing for a friend

A shelf of free things by Suraaj Chandra Jha. Books, research notes, whatever else
gets finished. No signup, no tracking, just files.

## Research notes

**THE LAST KNOWN GOOD STATE**, a recovery protocol for interrupted work. It
derives an eight-field handoff packet from recovery engineering and operating
practice, then sets out a falsifiable test using an executable interrupted job
queue. Reads on the web at `notes/last-known-good-state/`, with the full note and
laboratory beside it.

**CODEX SERAPHINIANUS**, a cryptanalysis of the script in Luigi Serafini's 1981
encyclopedia, and the interpretive translation that survives the negative result.
Reads on the web at `notes/codex-seraphinianus/`, with the full note as a PDF.

## Books

**CONVERSATIONS WITH CLAUDE**, a three-volume book about talking to machines,
written for readers who know nothing and read until they run their own agents.

- Volume One: THE INFINITE
- Volume Two: THE CONTEXT WINDOW
- Volume Three: PLEASE UPGRADE YOUR PLAN

Each PDF opens full screen. You press next.

The books and research notes are free to pass on whole, with the name kept on
them (CC BY-NC-ND 4.0). The executable laboratory is published without a
software licence; do not infer software permissions from the notes' Creative
Commons terms. Not affiliated with Anthropic, Luigi Serafini, or Rizzoli.

## Layout

`index.html` at the root is the shelf. Book PDFs are rendered elsewhere and copied
into `books/`. Each research note builds in place: `deck.json` holds the prose and
`build.py` renders it to `deck.html` and then to the published PDF. The PDF is
never hand-edited. Every PDF on the shelf is the same artifact:
1280x720 landscape pages, one idea per page, opening full screen. Fonts are OFL
licensed, with license texts in `fonts/`.
