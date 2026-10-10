#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

# The title block supplies the Markdown document's first heading in the PDF.
sed '1,2d' docs/report/world-engine-report.md | pandoc \
  --standalone --from markdown --to latex \
  --metadata title='Workflow environments, reliable evaluations, and useful post-training data' \
  --metadata author='World Engine technical research' \
  --metadata date='October 10, 2026' \
  --variable documentclass=article --variable papersize=letter \
  --variable fontsize=11pt --variable geometry:margin=0.85in \
  --variable colorlinks=true --variable linkcolor=researchblue \
  --variable urlcolor=researchblue --variable linestretch=1.05 \
  --include-in-header docs/report/pdf-header.tex \
  --output docs/report/world-engine-report.tex
tectonic docs/report/world-engine-report.tex --keep-logs
pdftotext -layout docs/report/world-engine-report.pdf docs/report/world-engine-report-text.txt
pdfinfo docs/report/world-engine-report.pdf > docs/report/world-engine-report-metadata.txt
pdfinfo -url docs/report/world-engine-report.pdf > docs/report/world-engine-report-links.txt
mkdir -p docs/report/rendered
pdftoppm -scale-to 1000 -png docs/report/world-engine-report.pdf docs/report/rendered/page
