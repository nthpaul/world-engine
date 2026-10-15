"use strict";

const $ = (id) => document.getElementById(id);
const stepLabels = ["Task", "State", "Observation", "Action", "Grade", "Explain it back"];
let lesson, progress, draftKey, timer, saving;
let revision = 0, savedRevision = 0, saveFailed = false, storageAvailable = true;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

async function request(url, options) {
  const response = await fetch(url, { cache: "no-store", ...options });
  if (!response.ok) throw new Error("Request failed");
  return response.json();
}

function saveStatus(text, error = false) {
  $("save-status").textContent = text;
  $("save-status").dataset.state = error ? "error" : "normal";
  $("retry-save").hidden = !error;
}

function payload() {
  return { step: progress.step, answers: { ...progress.answers }, checked: { ...progress.checked } };
}

function keepDraft() {
  try { localStorage.setItem(draftKey, JSON.stringify(payload())); }
  catch { storageAvailable = false; }
}

function changed() {
  revision += 1;
  keepDraft();
  saveFailed = false;
  saveStatus("Unsaved changes");
  clearTimeout(timer);
  timer = setTimeout(flush, 450);
}

async function flush() {
  clearTimeout(timer);
  if (saving) return saving;
  if (savedRevision === revision) return true;
  saving = (async () => {
    while (savedRevision !== revision) {
      const sentRevision = revision;
      const body = payload();
      saveStatus("Saving...");
      try {
        const result = await request("/api/progress", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        if (result.lessonId !== lesson.id || result.version !== 1) throw new Error("Unexpected save response");
        savedRevision = sentRevision;
        progress.updatedAt = result.updatedAt;
        if (savedRevision === revision) {
          try { localStorage.removeItem(draftKey); } catch { storageAvailable = false; }
          saveStatus("Saved on this computer");
          $("draft-notice").hidden = true;
        }
      } catch {
        saveFailed = true;
        keepDraft();
        saveStatus(storageAvailable ? "Not saved to disk. Draft kept in this browser." : "Not saved. Keep this page open.", true);
        return false;
      }
    }
    return true;
  })();
  try { return await saving; } finally { saving = undefined; }
}

function validProgress(value) {
  if (!value || !Number.isInteger(value.step) || value.step < 0 || value.step >= lesson.sections.length || !value.answers || typeof value.answers !== "object" || Array.isArray(value.answers) || !value.checked || typeof value.checked !== "object" || Array.isArray(value.checked)) return false;
  return Object.entries(value.answers).every(([id, answer]) => {
    const question = lesson.questions.find((item) => item.id === id);
    return question && typeof answer === "string" && answer.length <= 8000 && (question.kind === "written" || question.choices.some((choice) => choice.id === answer));
  }) && Object.entries(value.checked).every(([id, checked]) => lesson.questions.some((item) => item.id === id && item.kind === "choice") && typeof checked === "boolean");
}

function navigate(step) {
  progress.step = step;
  changed();
  render();
  $("section-title").focus();
  void flush();
}

function renderEvidence(evidence) {
  const figure = node("figure", "evidence");
  figure.append(node("div", "evidence-label", evidence.kind === "text" ? "Evidence / instructor notes" : "Actual recorded " + evidence.kind));
  if (evidence.kind === "text") {
    figure.append(node("pre", "", evidence.excerpt || "No excerpt available."));
  } else if (typeof evidence.mediaId === "string" && evidence.mediaId) {
    const media = node(evidence.kind === "video" ? "video" : "img");
    media.src = "/media/" + encodeURIComponent(evidence.mediaId);
    if (evidence.kind === "image") { media.alt = evidence.caption || "Recorded lesson evidence"; media.loading = "lazy"; }
    else { media.controls = true; media.preload = "metadata"; media.playsInline = true; media.setAttribute("aria-label", evidence.caption || "Recorded evidence video"); }
    media.addEventListener("error", () => { figure.append(node("p", "media-error", "This recording could not be loaded. The lesson and your answers remain available.")); }, { once: true });
    figure.append(media);
  } else figure.append(node("p", "media-error", "Evidence is not available for this step."));
  figure.append(node("figcaption", "", evidence.caption || ""));
  return figure;
}

function renderQuestion(question) {
  const area = node("section", "question");
  if (question.kind === "choice") {
    const fieldset = node("fieldset");
    fieldset.append(node("legend", "", question.prompt));
    const feedback = node("div", "feedback");
    feedback.setAttribute("role", "status");
    feedback.hidden = !progress.checked[question.id];
    const updateFeedback = () => { feedback.textContent = question.explanations?.[progress.answers[question.id]] || "Compare your choice with the recorded evidence, then bring your reasoning to discussion."; };
    const check = node("button", "primary-button", "Check my reasoning");
    check.disabled = !progress.answers[question.id];
    for (const choice of question.choices) {
      const label = node("label", "choice");
      const input = node("input");
      input.type = "radio"; input.name = question.id; input.value = choice.id;
      input.checked = progress.answers[question.id] === choice.id;
      input.addEventListener("change", () => {
        progress.answers[question.id] = choice.id;
        progress.checked[question.id] = false;
        feedback.hidden = true; check.disabled = false; changed();
      });
      label.append(input, node("span", "", choice.label)); fieldset.append(label);
    }
    check.addEventListener("click", () => { progress.checked[question.id] = true; updateFeedback(); feedback.hidden = false; changed(); void flush(); });
    updateFeedback(); area.append(fieldset, node("p", "question-note", "A prediction to discuss, not a score."), check, feedback);
  } else {
    const label = node("label");
    const title = node("h3", "", question.prompt);
    const textarea = node("textarea");
    textarea.id = "answer-" + question.id; textarea.maxLength = 8000;
    textarea.value = progress.answers[question.id] || "";
    label.htmlFor = textarea.id; label.append(title);
    textarea.addEventListener("input", () => { progress.answers[question.id] = textarea.value; changed(); updateReviewAnswers(); });
    const note = node("p", "question-note", "Draft saved automatically. Awaiting discussion, not automatic mastery.");
    note.id = "note-" + question.id; textarea.setAttribute("aria-describedby", note.id);
    area.append(label, textarea, note);
    if (question.reviewFocus) area.append(node("p", "question-note", question.reviewFocus));
  }
  return area;
}

function updateReviewAnswers() {
  const answers = $("review-answers");
  if (!answers) return;
  answers.replaceChildren();
  for (const question of lesson.questions) {
    const item = node("div", "review-item");
    const answer = progress.answers[question.id];
    const text = question.kind === "choice" ? question.choices.find((choice) => choice.id === answer)?.label : answer;
    item.append(node("h4", "", question.prompt), node("p", "review-answer", text?.trim() ? text : "Not answered yet."));
    answers.append(item);
  }
}

function renderReview() {
  const review = node("section", "review");
  review.append(node("h3", "", "Your answers, ready for a conversation"), node("p", "question-note", "Review what you wrote. Codex can read these saved answers when you ask to discuss Lesson 1."));
  const answers = node("div"); answers.id = "review-answers"; review.append(answers);
  const ready = node("button", "primary-button", "Ready for review");
  const message = node("p", "review-message"); message.setAttribute("role", "status");
  ready.addEventListener("click", async () => {
    ready.disabled = true;
    const saved = await flush();
    message.textContent = saved ? "Saved for discussion. Tell Codex: Lesson 1 is ready for review." : "Your answers are not saved to disk yet. Retry save before asking for review.";
    ready.disabled = false;
  });
  review.append(ready, message); return review;
}

function render() {
  const section = lesson.sections[progress.step];
  $("position").textContent = (progress.step + 1) + " of " + lesson.sections.length;
  for (const [index, button] of [...$("steps").children].entries()) {
    if (index === progress.step) button.setAttribute("aria-current", "step"); else button.removeAttribute("aria-current");
  }
  for (const part of document.querySelectorAll(".workflow [data-part]")) part.classList.toggle("is-current", part.dataset.part === ["task", "state", "observation", "action", "grade", "review"][progress.step]);
  const grid = node("div", "section-grid");
  const text = node("section");
  text.append(node("p", "eyebrow", section.kicker || stepLabels[progress.step]));
  const title = node("h2", "", section.title); title.id = "section-title"; title.tabIndex = -1;
  text.append(title, node("p", "summary", section.summary));
  const prose = node("div", "prose");
  for (const paragraph of section.paragraphs || []) prose.append(node("p", "", paragraph));
  text.append(prose);
  if (section.facts?.length) {
    const facts = node("dl", "facts");
    for (const fact of section.facts) { const row = node("div", "fact"); row.append(node("dt", "", fact.label), node("dd", "", fact.value)); facts.append(row); }
    text.append(facts);
  }
  const question = lesson.questions.find((item) => item.id === section.questionId);
  if (question) text.append(renderQuestion(question));
  grid.append(text);
  if (section.evidence) grid.append(renderEvidence(section.evidence)); else grid.classList.add("no-evidence");
  $("section-content").replaceChildren(grid);
  if (progress.step === lesson.sections.length - 1) { $("section-content").append(renderReview()); updateReviewAnswers(); }
  $("previous").disabled = progress.step === 0;
  $("next").hidden = progress.step === lesson.sections.length - 1;
}

async function boot() {
  try {
    const data = await request("/api/lesson");
    if (!data || data.id !== "gitlab-01" || data.version !== 1 || typeof data.contentHash !== "string" || !/^[a-f0-9]{64}$/.test(data.contentHash) || !Array.isArray(data.sections) || data.sections.length !== 6 || !Array.isArray(data.questions) || !data.questions.every((q) => typeof q.id === "string" && ["choice", "written"].includes(q.kind) && (q.kind !== "choice" || Array.isArray(q.choices)))) throw new Error("Invalid lesson");
    lesson = data; draftKey = "world-engine.learning." + lesson.id + ".v" + lesson.version + "." + lesson.contentHash;
    progress = await request("/api/progress");
    if (progress.version !== 1 || progress.lessonId !== lesson.id || !validProgress(progress)) throw new Error("Invalid saved progress");
    try {
      const stored = localStorage.getItem(draftKey);
      if (stored) {
        const draft = JSON.parse(stored);
        if (validProgress(draft)) { Object.assign(progress, draft); revision = 1; $("draft-notice").textContent = "An unsaved browser draft was recovered. Saving it to this computer now."; $("draft-notice").hidden = false; }
      }
    } catch { storageAvailable = false; }
    $("lesson-title").textContent = lesson.title;
    const taskDetails = node("details", "task-instruction");
    taskDetails.append(node("summary", "", "Original task and run"), node("p", "", lesson.task));
    const provenance = node("dl", "facts");
    for (const [label, value] of [["Model", lesson.model], ["Attempt", lesson.attemptId], ["Recorded source", lesson.sourceRevision]]) {
      const row = node("div", "fact"); row.append(node("dt", "", label), node("dd", "", value)); provenance.append(row);
    }
    taskDetails.append(provenance);
    $("steps").after(taskDetails);
    for (const [index, label] of stepLabels.entries()) {
      const button = node("button", "step"); button.append(node("span", "step-number", String(index + 1)), node("span", "", label)); button.addEventListener("click", () => navigate(index)); $("steps").append(button);
    }
    $("previous").addEventListener("click", () => navigate(progress.step - 1));
    $("next").addEventListener("click", () => navigate(progress.step + 1));
    $("retry-save").addEventListener("click", () => void flush());
    $("export").addEventListener("click", async (event) => { event.preventDefault(); if (await flush()) window.location.assign("/api/export"); });
    $("export").hidden = false; $("boot-state").hidden = true; $("lesson-shell").hidden = false;
    render(); saveStatus("Saved on this computer"); if (revision) void flush();
  } catch {
    const state = $("boot-state"); state.replaceChildren(node("p", "", "The lesson could not be opened. Your existing answers have not been changed."));
    const retry = node("button", "subtle-button", "Try again"); retry.addEventListener("click", () => window.location.reload()); state.append(retry);
    saveStatus("Lesson unavailable");
  }
}

window.addEventListener("pagehide", keepDraftOnExit);
function keepDraftOnExit() { if (progress && savedRevision !== revision) keepDraft(); }
window.addEventListener("beforeunload", (event) => { if (savedRevision !== revision || saveFailed) { keepDraftOnExit(); event.preventDefault(); event.returnValue = ""; } });
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden" && progress) { keepDraftOnExit(); void flush(); } });
void boot();
