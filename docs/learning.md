# Local recorded-attempt lesson

The learning page is separate from the workflow API, browser runner and model
providers. It displays an operator-prepared lesson from retained evidence and
saves the learner's answers locally. Opening or answering the lesson does not
start an attempt, call a model, change an original trace or regrade an outcome.

## Start

The operator supplies a private lesson JSON and a separate state path. Both must
be absolute paths, with existing parent directories and no symlink components.
Use a new state filename for a different lesson revision:

```sh
python3 learning/server.py \
  --lesson /absolute/private/lesson.json \
  --state /absolute/private/lesson-progress.sqlite3 \
  --port 5181
```

Open `http://127.0.0.1:5181`. The server binds only IPv4 loopback. It serves the
fixed `learning/static/index.html`, `styles.css` and `app.js` files, not a directory
listing. The console author owns those assets; the server requires no package
installation or external service.

## Lesson input

The version 1 document contains `id`, `title`, `attemptId`, `sourceRevision`,
`model`, `task`, `sections`, `questions` and a private `media` map. `model` and
`task` are display strings. Sections have `id`, `title`, `kicker`, `summary`,
`paragraphs` and `facts`; optional evidence contains an image/video media ID or
a text excerpt. Optional `questionId` refers to a declared question.

The current page is Lesson 1: it expects ID `gitlab-01`, version 1 and six
sections ordered Task, State, Observation, Action, Grade and Explain It Back.
The wider server input bounds do not imply other lessons are already authored.

Questions are `choice` or `written`. Choice questions declare unique choice IDs,
their labels and a `correctChoice`; optional explanations are keyed by choice ID.
Written questions can carry `reviewFocus`. These teaching answers are public
lesson content, not a protected runtime grader or model training payload.

The server validates the document before opening a state database. Lesson JSON
is limited to 2 MiB, sections/questions/media entries to 100 each, and registered
media to 512 MiB per file. Registered files must be regular PNG/JPG/JPEG/MP4/WebM
files without symlink components. The private map contains absolute paths;
`GET /api/lesson` omits it. Text, excerpts and screenshots are operator-reviewed
content: schema validation is not automatic secret redaction.

## HTTP contract

| Request | Result |
| --- | --- |
| `GET /api/lesson` | Validated lesson without the private media path map, plus computed `contentHash` |
| `GET /api/progress` | Latest saved progress, or the blank envelope below |
| `PUT /api/progress` | Atomically save a complete progress snapshot and return the saved envelope |
| `GET /api/export` | Download the latest persisted progress as JSON |
| `GET /media/<id>` | One exact registered media file; supports a single byte range |

The initial progress is:

```json
{"version":1,"lessonId":"gitlab-01","step":0,"answers":{},"checked":{},"updatedAt":null}
```

The returned `contentHash` is SHA256 of the canonical public lesson input,
excluding the private media map and the computed field itself. The input schema
does not accept `contentHash`. The page uses lesson ID, version and this hash
to separate local drafts, so changed questions or explanations cannot restore
an earlier revision's answers into a fresh state database. This is the same
existing SQLite lesson identity; it is not a hash of the media files.

PUT accepts exactly `step`, `answers` and `checked`. The step is an integer from
zero through the last section index. Answers are sparse maps from question ID
to a declared choice ID or a written string of at most 8000 characters. Empty
written answers are valid. Checked flags are sparse choice-question-ID maps
containing literal booleans; written questions cannot have checked flags.
Unknown fields, IDs, choices and coerced boolean/numeric values are rejected.

Writes require `application/json`, an explicit non-chunked Content-Length and
at most 64 KiB. Duplicate JSON keys are rejected. Host must exactly match a
loopback authority and this server's port. If Origin is present, it must exactly
match that authority's HTTP origin. Cross-site browser requests are rejected.
Rejected writes leave current progress and revision history unchanged. There is
no reset route. PUT replaces the latest snapshot, so two tabs can overwrite
each other's current edits; retained revisions preserve earlier saves.

## Persistence and limits

The SQLite database carries a learning-specific application ID and the public
lesson's content hash. The server refuses unrelated existing databases and
state paths that collide with lesson, registered media or static assets. A
changed public lesson hash requires a new state path; it does not erase earlier
answers. A new state file uses mode 0600. Each accepted save inserts a revision
and updates current progress in one transaction. Restarting reloads those edits.

History is retained, not pruned: after 10000 saves or the 8192-page database ceiling,
new saves fail and earlier data remains. The ordinary 4096-byte SQLite page size
gives a 32 MiB database ceiling. The server processes one connection at a time
with a five-second socket timeout and streams media in 64 KiB chunks. It is a
trusted, single-user local lesson server, not authenticated hosting, tenant
isolation or protection against a privileged local process changing its files.
CSP restricts content to this origin and responses include no-sniff headers.
Seeking or leaving a video can disconnect its download. Broken pipes and
connection resets close that connection without a second response; filesystem
and other read errors still return a failure.

## Verify

```sh
uv run python -m pytest tests/test_learning_server.py -q
uv run ruff check learning/server.py tests/test_learning_server.py
```

Tests use temporary lessons, media and databases. They verify restart persistence,
revision rollback, original-file preservation, rejected writes, path/origin/body
boundaries and media range handling. They do not perform inference or collect
new workflow evidence.

For the recorded lesson, use a separate fresh QA database and an unused port,
then run the browser check with the existing console's Playwright installation:

```sh
python3 learning/server.py \
  --lesson /absolute/private/lesson.json \
  --state /absolute/private/fresh-qa.sqlite3 \
  --port 5182
node scripts/learning-ui-qa.mjs \
  --url http://127.0.0.1:5182/ \
  --output /absolute/private/fresh-qa-output
```

The check refuses a previously used state or existing output directory. It saves
test answers, exercises feedback, reload/retry, export, desktop video playback
and desktop/mobile layouts. Never run it against the learner's state database.
Stop the QA server when finished. The lesson's media and the browser recordings
are distinct artifacts; neither is a new rollout or training result.

When the learner asks for review, inspect the saved JSON export or read
`progress.payload` from the SQLite database read-only. Discuss the written
answers; checked flags and page visits are not proof of understanding.
