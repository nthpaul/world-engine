#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

sed '1,4d' docs/report/advanced-environment-labs.md | pandoc \
  --standalone --from markdown --to latex \
  --metadata title='Advanced environment labs' \
  --metadata author='World Engine technical research' \
  --metadata date='October 10, 2026' \
  --variable documentclass=article --variable papersize=letter \
  --variable fontsize=11pt --variable geometry:margin=0.8in \
  --variable colorlinks=true --variable linkcolor=researchblue \
  --variable urlcolor=researchblue --variable linestretch=1.0 \
  --include-in-header docs/report/pdf-header.tex \
  --include-in-header <(printf '%s\n' \
    '\makeatletter' \
    '\renewcommand{\maketitle}{\begingroup\centering' \
    '{\LARGE\@title\par}\vspace{0.6em}' \
    '{\normalsize\@author\par}\vspace{0.3em}' \
    '{\small\@date\par}\endgroup\vspace{1em}}' \
    '\makeatother') \
  --output docs/report/advanced-environment-labs.tex

if [[ "${1:-}" == "--source-only" ]]; then
  exit 0
fi

tectonic docs/report/advanced-environment-labs.tex --keep-logs
pdftotext -layout docs/report/advanced-environment-labs.pdf docs/report/advanced-environment-labs-text.txt
pdfinfo docs/report/advanced-environment-labs.pdf > docs/report/advanced-environment-labs-metadata.txt
pdfinfo -url docs/report/advanced-environment-labs.pdf > docs/report/advanced-environment-labs-links.txt
mkdir -p docs/report/rendered
qa_dir="$(mktemp -d docs/report/rendered/advanced-XXXXXX)"
pdftoppm -r 120 -png docs/report/advanced-environment-labs.pdf "$qa_dir/page"
printf 'QA renders: %s\n' "$qa_dir"
