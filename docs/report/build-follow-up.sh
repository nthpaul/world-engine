#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

sed '1,4d' docs/report/world-engine-follow-up.md | pandoc \
  --standalone --from markdown --to latex \
  --metadata title='World Engine: follow-up evidence and boundaries' \
  --metadata author='World Engine technical research' \
  --metadata date='October 10, 2026' \
  --variable documentclass=article --variable papersize=letter \
  --variable fontsize=11pt --variable geometry:margin=0.85in \
  --variable colorlinks=true --variable linkcolor=researchblue --variable filecolor=researchblue \
  --variable urlcolor=researchblue --variable linestretch=1.02 \
  --include-in-header docs/report/pdf-header.tex \
  --output docs/report/world-engine-follow-up.tex

if [[ "${1:-}" == "--source-only" ]]; then
  exit 0
fi

tectonic docs/report/world-engine-follow-up.tex --only-cached --keep-logs
if rg -q 'Overfull|undefined references|undefined citations' docs/report/world-engine-follow-up.log; then
  printf 'PDF layout/reference validation failed; inspect the build log.\n' >&2
  exit 1
fi
pdftotext -layout docs/report/world-engine-follow-up.pdf docs/report/world-engine-follow-up-text.txt
pdfinfo docs/report/world-engine-follow-up.pdf > docs/report/world-engine-follow-up-metadata.txt
pdfinfo -url docs/report/world-engine-follow-up.pdf > docs/report/world-engine-follow-up-links.txt
mkdir -p docs/report/rendered
qa_dir="$(mktemp -d docs/report/rendered/follow-up-XXXXXX)"
pdftoppm -r 120 -png docs/report/world-engine-follow-up.pdf "$qa_dir/page"
printf 'QA renders: %s\n' "$qa_dir"
