// Worklet 15 — final project report generator.
// Mirrors the chapter structure of the SDP final report.

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, PageBreak,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle, ImageRun,
  TableOfContents, LevelFormat, PositionalTab, PositionalTabAlignment,
  PositionalTabLeader, convertInchesToTwip,
} = require("docx");

const FIGS = path.join(__dirname, "figs");
const OUT = process.argv[2];

// A4 usable width with 1" margins
const W = 9026;
const FONT = "Times New Roman";

// ---------------------------------------------------------------- helpers
const P = (text, opts = {}) =>
  new Paragraph({
    alignment: opts.align || AlignmentType.JUSTIFIED,
    spacing: { after: opts.after === undefined ? 140 : opts.after,
               before: opts.before || 0, line: 276 },
    indent: opts.indent,
    children: [new TextRun({ text, bold: opts.bold, italics: opts.italics,
                             size: opts.size || 22, font: FONT,
                             color: opts.color })],
  });

const Rich = (runs, opts = {}) =>
  new Paragraph({
    alignment: opts.align || AlignmentType.JUSTIFIED,
    spacing: { after: opts.after === undefined ? 140 : opts.after, line: 276 },
    children: runs.map(r =>
      new TextRun({ text: r.t, bold: r.b, italics: r.i, font: r.m ? "Consolas" : FONT,
                    size: r.m ? 19 : (opts.size || 22) })),
  });

const H1 = text => new Paragraph({
  heading: HeadingLevel.HEADING_1, pageBreakBefore: true,
  spacing: { before: 240, after: 240 },
  children: [new TextRun({ text, bold: true, size: 30, font: FONT })],
});
const H1np = text => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 240, after: 240 },
  children: [new TextRun({ text, bold: true, size: 30, font: FONT })],
});
const H2 = text => new Paragraph({
  heading: HeadingLevel.HEADING_2, spacing: { before: 240, after: 120 },
  children: [new TextRun({ text, bold: true, size: 25, font: FONT })],
});
const H3 = text => new Paragraph({
  heading: HeadingLevel.HEADING_3, spacing: { before: 180, after: 100 },
  children: [new TextRun({ text, bold: true, size: 23, font: FONT })],
});

const Bullet = (text, lvl = 0) => new Paragraph({
  numbering: { reference: "bullets", level: lvl },
  spacing: { after: 80, line: 276 },
  children: [new TextRun({ text, size: 22, font: FONT })],
});

const Caption = text => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 80, after: 220 },
  children: [new TextRun({ text, size: 19, italics: true, font: FONT })],
});

const cell = (text, { b = false, w, bg, align } = {}) => new TableCell({
  width: { size: w, type: WidthType.DXA },
  shading: bg ? { type: ShadingType.CLEAR, fill: bg } : undefined,
  margins: { top: 60, bottom: 60, left: 90, right: 90 },
  children: [new Paragraph({
    alignment: align || AlignmentType.LEFT,
    spacing: { after: 0, line: 240 },
    children: [new TextRun({ text: String(text), bold: b, size: 19, font: FONT })],
  })],
});

function table(header, rows, widths) {
  const sum = widths.reduce((a, b) => a + b, 0);
  const scaled = widths.map(x => Math.round(x / sum * W));
  return new Table({
    columnWidths: scaled,
    width: { size: W, type: WidthType.DXA },
    rows: [
      new TableRow({
        tableHeader: true,
        children: header.map((h, i) => cell(h, { b: true, w: scaled[i], bg: "E8EAF0" })),
      }),
      ...rows.map(r => new TableRow({
        children: r.map((c, i) => cell(c, { w: scaled[i] })),
      })),
    ],
  });
}

function figure(file, caption, h = 435) {
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { before: 160, after: 0 },
      children: [new ImageRun({
        type: "jpg", data: fs.readFileSync(path.join(FIGS, file)),
        transformation: { width: 580, height: h },
      })],
    }),
    Caption(caption),
  ];
}

const SP = (n = 1) => Array.from({ length: n },
  () => new Paragraph({ spacing: { after: 0 }, children: [] }));

// ---------------------------------------------------------------- content
const doc = [];

// ======================= TITLE PAGE =======================
const T = (t, { sz = 24, b = false, i = false, after = 120 } = {}) =>
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after },
    children: [new TextRun({ text: t, bold: b, italics: i, size: sz, font: FONT })] });

doc.push(
  T("SCHOOL OF COMPUTER SCIENCE AND ENGINEERING", { sz: 26, b: true, after: 200 }),
  T("KLE TECHNOLOGICAL UNIVERSITY, HUBBALLI", { sz: 22, after: 420 }),
  T("Project report on", { sz: 22, i: true, after: 160 }),
  T("WORKLET 15", { sz: 30, b: true, after: 60 }),
  T("Executive Decision Support System", { sz: 34, b: true, after: 60 }),
  T("An agentic pipeline from a free-text request to an approved,",
    { sz: 22, i: true, after: 20 }),
  T("versioned and reversible decision brief", { sz: 22, i: true, after: 420 }),
  T("Submitted in partial fulfillment of the requirements of the course",
    { sz: 22, after: 60 }),
  T("Agentic AI  (26ECAC401)", { sz: 24, b: true, after: 420 }),
  T("Submitted By — Team 11, A Division", { sz: 22, b: true, after: 160 }),
  T("Nakul Singh", { sz: 22, after: 60 }),
  T("Riya Ajit Magadum", { sz: 22, after: 60 }),
  T("Surabhi P", { sz: 22, after: 60 }),
  T("Shreya Vasavad", { sz: 22, after: 420 }),
  T("School of Computer Science and Engineering", { sz: 22, after: 60 }),
  T("Computer Science and Engineering (Artificial Intelligence)",
    { sz: 22, after: 200 }),
  T("2026 – 2027", { sz: 24, b: true, after: 0 }),
);

// ======================= ABSTRACT =======================
doc.push(H1("ABSTRACT"));
doc.push(P(
  "An institution measures itself through Key Performance Indicators, but the " +
  "process that turns those indicators into a decision is almost entirely " +
  "manual. A Principal asking how the institution is performing sets off days " +
  "of email: departments export spreadsheets, a coordinator sums them by hand, " +
  "and a brief is assembled in which nobody can say precisely which figure came " +
  "from which system, which figures were provisional, or which numbers were " +
  "counted twice. Three failures recur. Scope is never agreed, so two people " +
  "answer the same question differently. Department returns are summed naively, " +
  "so jointly owned records are double counted. Provisional figures are read as " +
  "final because nothing on the page says otherwise."));
doc.push(P(
  "This worklet presents an Executive Decision Support System built as an " +
  "agentic pipeline. A free-text request from leadership becomes an approved, " +
  "published and reversible decision brief, and the human is asked for exactly " +
  "three things: the request, answers to whatever the agent says it is missing, " +
  "and an approval decision. Everything between those points runs unattended. " +
  "The system is deliberately built so that refusing is a first-class outcome: " +
  "it will not invent a scope, it will not read a period it has no authorisation " +
  "for, it will not publish without a named human, and when it cannot repair a " +
  "defect it escalates and publishes nothing."));
doc.push(P(
  "The implementation spans fourteen laboratory exercises covering the agent " +
  "loop, typed tool calling, reusable skills, memory and retrieval, an MCP-style " +
  "governed connector, a controlled runtime, an execution graph, a parallel " +
  "agent swarm, evidence grounding, self-repair, a spec-driven acceptance " +
  "factory, governance, domain specialists and capstone integration. A single " +
  "end-to-end run executes nineteen stages in 331 ms of agent time, dispatches " +
  "eight department agents in parallel at 3.2x the serial cost, reconciles 174 " +
  "claimed publications down to 171 by de-duplicating jointly authored records, " +
  "repairs one defective KPI row out of nine without touching the other eight, " +
  "passes twenty-two acceptance tests derived from the request itself, and stops " +
  "at a role-checked approval gate. The whole system is verified by 284 " +
  "automated checks that run without a browser, and every refusal path is " +
  "proven, not merely claimed."));

// ======================= ACKNOWLEDGEMENT =======================
doc.push(H1("ACKNOWLEDGEMENT"));
doc.push(P(
  "We thank the School of Computer Science and Engineering, KLE Technological " +
  "University, for the structure of the Agentic AI course, whose fourteen " +
  "laboratory exercises gave this worklet both its scope and its discipline. " +
  "Each lab arrived with an explicit acceptance criterion, and holding the " +
  "implementation to those criteria rather than to our own judgement is what " +
  "kept the system honest."));
doc.push(P(
  "We are grateful to our course faculty for the review sessions. The questions " +
  "asked there — what exactly are you using for memory, what tool performs " +
  "retrieval, and what is this system actually for — were more useful than any " +
  "approval would have been. Several parts of this report exist because those " +
  "questions exposed gaps between what the system did and what we could " +
  "demonstrate it did."));
doc.push(P(
  "We also thank the peer team who evaluated this artifact. Their scoring " +
  "identified, correctly, that the capabilities most weakly demonstrated were " +
  "the runtime controls and the absence of cloud build and deployment; both are " +
  "recorded in this report as stated limitations rather than quietly omitted."));

// ======================= CONTENTS =======================
doc.push(H1("CONTENTS"));
doc.push(new TableOfContents("Table of Contents", {
  hyperlink: true, headingStyleRange: "1-3",
}));

// ======================= LIST OF TABLES =======================
doc.push(H1("LIST OF TABLES"));
const tableList = [
  ["Table 2.1", "Functional requirements and their origin"],
  ["Table 2.2", "Non-functional requirements"],
  ["Table 2.3", "Software requirements"],
  ["Table 3.1", "Responsibilities of each architectural layer"],
  ["Table 4.1", "Resources exposed by the MCP connector"],
  ["Table 4.2", "Metrics in the department fact tables"],
  ["Table 5.1", "Course expectations, per lab, and how each was met"],
  ["Table 5.2", "Stage-by-stage trace of one complete run"],
  ["Table 5.3", "KPI scorecard produced by the run"],
  ["Table 5.4", "Department breakdown for placement percentage"],
  ["Table 5.5", "How the run changes with the request"],
  ["Table 5.6", "Refusal paths and their outcomes"],
  ["Table 5.7", "Automated verification coverage"],
];
tableList.forEach(([n, t]) => doc.push(new Paragraph({
  spacing: { after: 70 },
  children: [new TextRun({ text: `${n}   ${t}`, size: 22, font: FONT })],
})));

// ======================= LIST OF FIGURES =======================
doc.push(H1("LIST OF FIGURES"));
const figList = [
  ["Figure 1.1", "The three recurring failures in manual KPI reporting"],
  ["Figure 3.1", "System architecture: the plan becomes the contract"],
  ["Figure 5.1", "The agent refuses a vague request and asks what it is missing"],
  ["Figure 5.2", "A run in progress, narrating the stage it is executing"],
  ["Figure 5.3", "The published KPI scorecard"],
  ["Figure 5.4", "Department-level drill-down for placement percentage"],
];
figList.forEach(([n, t]) => doc.push(new Paragraph({
  spacing: { after: 70 },
  children: [new TextRun({ text: `${n}   ${t}`, size: 22, font: FONT })],
})));

// ======================= 1 INTRODUCTION =======================
doc.push(H1("1.  INTRODUCTION"));
doc.push(P(
  "This chapter establishes why an institution needs a decision support system " +
  "that behaves like an agent rather than a report generator, what the system " +
  "is required to do, and the constraints under which it was built."));

doc.push(H2("1.1  Sustainable Development Goal (SDG)"));
doc.push(P(
  "This worklet addresses SDG 4, Quality Education, and specifically target 4.3, " +
  "which concerns equal access to quality technical and tertiary education. " +
  "Quality in a technical institution is governed by measurable indicators — " +
  "pass percentage, course-outcome attainment, research output, placement rate " +
  "and budget utilisation — and those indicators are the basis on which NIRF and " +
  "NAAC assess an institution. An institution that cannot see its own indicators " +
  "reliably cannot improve them deliberately."));
doc.push(P(
  "The contribution here is not another dashboard. It is a decision process in " +
  "which every figure is traceable to the system it came from, every claim " +
  "carries its evidence, department-level inequity is made visible rather than " +
  "averaged away, and no brief reaches leadership without a named human " +
  "accepting it. The system also addresses SDG 9 in its emphasis on auditable " +
  "and accountable institutional infrastructure."));
doc.push(P(
  "The department breakdown is where the SDG relevance is most concrete. The " +
  "institution-wide placement figure of 75.12 per cent conceals a range from " +
  "92.98 per cent in Computer Science to 50.88 per cent in Biotechnology. A " +
  "single institutional average, reported alone, hides exactly the inequity that " +
  "SDG 4 asks an institution to address."));

doc.push(H2("1.2  Motivation"));
doc.push(P(
  "The motivation came from observing how institutional reporting actually " +
  "works. A request for a performance review initiates a chain of manual steps, " +
  "each of which loses information. Departments export what they have; a " +
  "coordinator consolidates them in a spreadsheet; figures are rounded for " +
  "presentation; and the final brief contains numbers whose provenance has been " +
  "lost somewhere between the export and the slide."));
doc.push(P(
  "Three specific failures motivated the design, and each has a direct " +
  "counterpart in the system."));
doc.push(Bullet(
  "Scope is never pinned down. Asked to analyse performance, two analysts " +
  "produce different briefs because nobody agreed which domains, which period, " +
  "which KPI set or which targets were in scope. The system refuses to begin " +
  "until all six of these are settled."));
doc.push(Bullet(
  "Department returns are summed naively. A paper authored jointly by two " +
  "departments is reported by both, and a naive total overstates research " +
  "output. The system reconciles by record identifier rather than summing " +
  "counts, which removes three double-counted publications from a claimed 174."));
doc.push(Bullet(
  "Provisional figures are read as final. A budget utilisation figure that has " +
  "not been closed by Accounts looks identical to one that has. The system " +
  "carries figure status with every value and surfaces it on the face of the " +
  "brief."));
doc.push(P(
  "A fourth motivation emerged during development. A rounding rule can turn a " +
  "miss into a pass: an institution pass percentage of 91.85 per cent, rounded " +
  "to one decimal, reads as 92.0 and appears to meet a target of 92.0. The " +
  "system detects this condition and reports the unrounded figure with an " +
  "explicit warning."));

doc.push(H2("1.3  Literature Review / Survey"));
doc.push(P(
  "The design draws on four strands of recent work in agentic systems, and on " +
  "the course's own fourteen-lab structure which organises them."));
doc.push(P(
  "Tool-using agents. The distinction between a language model that produces " +
  "text and an agent that acts on the world is the ability to call typed tools " +
  "and observe results. The ReAct formulation of interleaved reasoning and " +
  "acting, and the schema-constrained function-calling interfaces now standard " +
  "in commercial model APIs, establish that tool arguments should be validated " +
  "against a declared schema before execution rather than parsed from prose. " +
  "This worklet applies that principle strictly: every computation passes " +
  "through a router that validates required arguments, types and enumerations, " +
  "and the arithmetic is performed in Python, never produced by generation."));
doc.push(P(
  "Model Context Protocol. The emergence of MCP as a standard for exposing data " +
  "sources to agents establishes a useful separation: a server advertises " +
  "resources with typed parameters and required scopes, and a client holds a " +
  "token. The agent therefore discovers capability rather than being " +
  "hard-coded against a data source, and authorisation is expressed as data. " +
  "The connector in this worklet follows that shape, with three interchangeable " +
  "backends behind one interface."));
doc.push(P(
  "Graph-based orchestration. Frameworks such as LangGraph argue that agent " +
  "control flow should be an explicit graph with conditional edges and cycles, " +
  "rather than control flow hidden inside prompt text. An explicit graph can be " +
  "validated for reachability before anything executes, and a repair cycle can " +
  "be expressed as a back-edge rather than as a retry loop buried in a function. " +
  "This worklet builds such a graph and validates it on construction."));
doc.push(P(
  "Reliability and evaluation. Work on self-healing pipelines and on evaluation " +
  "harnesses for generated artifacts converges on a common conclusion: the tests " +
  "an artifact must pass should be derived from its specification rather than " +
  "written once and reused. This worklet derives its acceptance suite from the " +
  "locked plan, so narrowing the request from four domains to one reduces the " +
  "suite from twenty-one tests to fifteen."));
doc.push(P(
  "The gap this worklet addresses is integration. Each of these ideas is " +
  "normally demonstrated in isolation. What is less often shown is a single run " +
  "in which the plan derived from a conversation determines which tools execute, " +
  "which agents are dispatched, which evidence is required, which tests are " +
  "generated and which human is permitted to approve the result."));

doc.push(H2("1.4  Problem Statement"));
doc.push(P(
  "To design and implement an agentic decision support system that converts a " +
  "free-text request from institutional leadership into an approved, versioned " +
  "and reversible decision brief, such that every figure is traceable to an " +
  "authorised source system, department-level variation is preserved rather " +
  "than averaged away, conflicting departmental claims are reconciled rather " +
  "than summed, and no result reaches a human reader without passing a test " +
  "suite derived from the request itself.", { after: 180 }));

doc.push(H2("1.5  Problem Analysis"));
doc.push(P(
  "Two design principles emerged from analysing the failures described in " +
  "Section 1.2. Both are stated here because they explain structural decisions " +
  "that appear throughout the implementation."));

doc.push(H3("1.5.1  Design principle 1: the plan is the contract"));
doc.push(P(
  "A system that accepts an ambiguous request and produces a confident answer " +
  "has not solved the ambiguity; it has concealed it. The first design principle " +
  "is therefore that the agent must converge on an explicit, inspectable plan " +
  "before any data is read, and that this plan — not the original request — is " +
  "what the remainder of the system obeys."));
doc.push(P(
  "This has a consequence that distinguishes an agentic system from a scripted " +
  "one. Because the plan determines which KPIs are computed, which domain packs " +
  "are invoked and which acceptance tests are generated, changing an answer in " +
  "the clarifying conversation changes what executes, not merely what is " +
  "printed. A request narrowed to Placement produces three KPIs and a fifteen-" +
  "test suite where the full request produces nine KPIs and a twenty-one-test " +
  "suite."));
doc.push(P(
  "It also determines how revision works. Feedback on a published brief patches " +
  "the existing plan in place rather than regenerating it, so the fields the " +
  "feedback did not mention remain provably untouched."));

doc.push(H3("1.5.2  Design principle 2: control flow and execution are separate"));
doc.push(P(
  "The second principle separates the decision about what runs next from the " +
  "mechanism that runs it. The order of stages, the repair cycle and the " +
  "approve-or-reject branch are edges in an explicit graph. The execution of " +
  "any single stage is the responsibility of a runtime that owns four things " +
  "the agent is not permitted to own: budgets, an append-only audit log, " +
  "checkpoints, and human approval gates."));
doc.push(P(
  "The practical benefit is that properties the system needs are obtained once " +
  "rather than per stage. Because every stage executes through the same runtime, " +
  "every stage is budget-checked, audited and checkpointed without any stage " +
  "having to arrange it. The pause at the approval gate is not a special case " +
  "either: it is the same checkpoint-and-resume mechanism that makes a crashed " +
  "run recoverable, which is why resuming after approval replays fifteen " +
  "completed stages without re-executing any of them."));

doc.push(H3("1.5.3  Scope and constraints"));
doc.push(P("The following constraints were fixed at the outset."));
doc.push(Bullet(
  "The data is synthetic and generated by the project. No real student, staff " +
  "or financial record is used, and no institutional system is accessed."));
doc.push(Bullet(
  "The system must run on a single machine with no network access, no API key " +
  "and no database server, so that it is reproducible by any evaluator."));
doc.push(Bullet(
  "Every laboratory exercise must remain independently runnable, since each is " +
  "assessed against its own acceptance criterion."));
doc.push(Bullet(
  "The agent proposes; a named human disposes. No configuration permits " +
  "automatic publication."));

doc.push(H2("1.6  Objectives"));
doc.push(P("The worklet set out to achieve the following."));
[
  "Build an agent loop that refuses to act on an under-specified request and " +
  "converges on an explicit plan through clarifying questions.",
  "Make that plan the operative contract, so that the answers given genuinely " +
  "determine which computations, agents and tests execute.",
  "Compute every published figure through schema-validated tool calls rather " +
  "than by generation, and attach the source system to each.",
  "Expose all institutional data through a single governed connector with " +
  "typed resources and scoped authorisation.",
  "Execute every stage inside a runtime that enforces budgets, maintains an " +
  "append-only audit and checkpoints after each action.",
  "Express the stage order, the repair cycle and the approval branch as a " +
  "validated graph with explicit escalation exits.",
  "Dispatch per-department agents in parallel and reconcile their conflicting " +
  "claims by identity rather than by summation.",
  "Ground every claim in an authorised source, and drop any claim that cannot " +
  "be grounded.",
  "Detect constraint violations and repair them minimally, escalating when " +
  "repair is not possible.",
  "Derive the acceptance suite from the agreed specification and prevent any " +
  "result from reaching a human without a fully passing report.",
  "Enforce role-checked approval, versioning, rollback and redaction.",
  "Verify the whole system through automated checks that require no browser.",
].forEach(o => doc.push(Bullet(o)));

// ======================= 2 REQUIREMENT ANALYSIS =======================
doc.push(H1("2.  REQUIREMENT ANALYSIS"));
doc.push(P(
  "The requirements below are the expectations the system was built to meet. " +
  "They come from two places: the course's fourteen laboratory exercises, each " +
  "of which states an acceptance criterion, and the problem analysis in " +
  "Chapter 1. Chapter 5 returns to each one and records how it was met and " +
  "what evidence demonstrates it."));

doc.push(H2("2.1  Functional Requirements"));
doc.push(table(
  ["ID", "Requirement", "Origin"],
  [
    ["FR-1", "The agent shall refuse an under-specified request and ask only for the requirements that are still missing.", "Lab 1"],
    ["FR-2", "The locked plan shall determine which KPIs are computed, which domain packs are invoked and which tests are derived.", "Lab 1, 11"],
    ["FR-3", "Every KPI shall be computed by a schema-validated tool call, never by text generation.", "Lab 2"],
    ["FR-4", "A single reusable skill shall be applied across every domain in scope.", "Lab 3"],
    ["FR-5", "The system shall recall prior context before planning and archive each release afterwards, append-only.", "Lab 4"],
    ["FR-6", "All data access shall pass through one connector that checks scope before serving.", "Lab 5"],
    ["FR-7", "Every action shall be logged with inputs and outputs, and a crashed run shall resume from its last checkpoint.", "Lab 6"],
    ["FR-8", "Stage order, the repair cycle and the approval branch shall be edges in a validated graph.", "Lab 7"],
    ["FR-9", "Department agents shall run in parallel, and their conflicting claims shall be reconciled by identity.", "Lab 8"],
    ["FR-10", "Every published claim shall carry an in-scope source, a locator and a value; ungrounded claims shall be dropped.", "Lab 9"],
    ["FR-11", "Constraint violations shall be diagnosed and repaired minimally; unrepairable defects shall escalate.", "Lab 10"],
    ["FR-12", "The acceptance suite shall be derived from the specification, and no artifact shall reach a human without a fully green report.", "Lab 11"],
    ["FR-13", "Approval shall be role-checked; releases shall be versioned, reversible and audited; detail shall be redacted by access level.", "Lab 12"],
    ["FR-14", "Domain specialists shall draft options and risks against their own output schema.", "Lab 13"],
    ["FR-15", "The integration layer shall add no new capability, only wiring.", "Lab 14"],
    ["FR-16", "Each KPI shall carry a department-level breakdown judged against the same target as the institution figure.", "Ch. 1.2"],
  ],
  [8, 62, 16]));
doc.push(Caption("Table 2.1  Functional requirements and their origin"));

doc.push(H2("2.2  Non Functional Requirements"));
doc.push(table(
  ["ID", "Requirement", "Acceptance"],
  [
    ["NFR-1", "Determinism — the same request must produce the same figures on every run.", "284 automated checks assert fixed values"],
    ["NFR-2", "Reproducibility — the system must run with no network, no API key and no database server.", "Three Python dependencies; data ships with the repository"],
    ["NFR-3", "Auditability — every action, its budget at the time and its outcome must be recoverable after the run.", "35 append-only audit entries per run"],
    ["NFR-4", "Boundedness — a run must not spend unlimited actions, connector calls or wall-clock time.", "Budget enforced before every action"],
    ["NFR-5", "Transparency — a reader must be able to see what the agent is doing while it does it.", "Per-stage narration naming the call being made"],
    ["NFR-6", "Latency — an unattended run should complete fast enough to demonstrate live.", "331 ms of agent time for nineteen stages"],
    ["NFR-7", "Testability — the user interface must be verifiable without a browser.", "AppTest drives both dashboards headlessly"],
    ["NFR-8", "Separation of concerns — presentation code must not compute or judge any value.", "pipeline_ui.py receives finished values only"],
  ],
  [8, 48, 30]));
doc.push(Caption("Table 2.2  Non-functional requirements"));

doc.push(H2("2.3  Hardware Requirements"));
doc.push(P(
  "The system has no special hardware requirement, which is itself a design " +
  "outcome: all computation is ordinary Python arithmetic over tabular data, " +
  "with no model inference in the execution path. It was developed and " +
  "demonstrated on an Apple silicon laptop with 16 GB of memory. A complete run " +
  "uses 331 ms of agent time and well under 100 MB of resident memory. No GPU is " +
  "required at any point. The parallel swarm uses eight operating-system threads, " +
  "so any machine with a modern multi-core processor reproduces the reported " +
  "speed-up; on a single core the swarm still completes correctly, returning the " +
  "same figures with no speed-up."));

doc.push(H2("2.4  Software Requirements"));
doc.push(table(
  ["Component", "Version", "Purpose"],
  [
    ["Python", "3.12", "Implementation language for the engine and both dashboards"],
    ["Streamlit", "1.45.1", "Both user interfaces, and the headless AppTest harness"],
    ["pandas", "2.x", "Tabular display in the dashboards"],
    ["altair", "5.x", "Charting in the lab-by-lab dashboard"],
    ["Standard library", "—", "csv, sqlite3, json, re, math, threading, concurrent.futures, dataclasses, pathlib"],
    ["google-genai", "optional", "Gemini integration in Labs 1 and 2; a deterministic fallback runs when no key is present"],
    ["Jupyter / Colab", "—", "Execution environment for the fourteen lab notebooks"],
  ],
  [20, 14, 66]));
doc.push(Caption("Table 2.3  Software requirements"));
doc.push(P(
  "The dependency list is deliberately short. There is no orchestration " +
  "framework, no vector database, no embedding model and no message broker. " +
  "Retrieval is hand-written TF-IDF with cosine similarity; the graph, the " +
  "runtime and the connector are implemented directly. This was a conscious " +
  "trade: the system is slower to write but every mechanism is inspectable, " +
  "which matters when the acceptance criterion for a lab is that a specific " +
  "behaviour can be demonstrated."));

// ======================= 3 SYSTEM DESIGN =======================
doc.push(H1("3.  SYSTEM DESIGN"));

doc.push(H2("3.1  Architectural Framework / System Design"));
doc.push(P(
  "The architecture has one organising idea: the conversation produces a plan, " +
  "the plan produces a specification, and the specification is what every " +
  "subsequent layer obeys. Figure 3.1 shows the resulting flow."));
doc.push(new Paragraph({
  alignment: AlignmentType.LEFT, spacing: { before: 120, after: 120 },
  children: [
    "request  ──►  Lab 1 clarify loop  ──►  locked plan  ──►  SPECIFICATION",
    "                                                              │",
    "        ┌─────────────────────────────────────────────────────┘",
    "        ▼",
    "   Lab 7  GRAPH — decides the order        Lab 6  RUNTIME — executes it",
    "   ├─ 18 nodes, 21 edges                   ├─ budgets  (actions/calls/seconds)",
    "   ├─ one back-edge for the repair cycle   ├─ audit    (append-only)",
    "   └─ four escalation exits                ├─ checkpoint after every action",
    "                                           └─ gates    (ApprovalRequired)",
    "        │",
    "        ├─ Lab 4   recall ─────── TF-IDF + cosine over an append-only archive",
    "        ├─ Lab 5   connector ──── MCP server, 4 resources, 3 backends",
    "        ├─ Lab 8   swarm ──────── 8 department agents in parallel, reconcile",
    "        ├─ Lab 3   skill ──────── one reusable domain review across domains",
    "        ├─ Lab 2   tools ──────── schema-validated calls; Python computes",
    "        ├─ Lab 13  specialists ── 4 domain packs draft options and risks",
    "        ├─ Lab 9   grounding ──── source + locator + value, or the claim is dropped",
    "        ├─ Lab 10  validate ───── fail → diagnose → minimal repair → re-validate",
    "        ├─ Lab 11  acceptance ─── suite derived from the spec, gates the human",
    "        └─ Lab 12  governance ─── role-checked approval, versioning, rollback",
  ].map(l => new TextRun({ text: l, font: "Consolas", size: 15, break: 1 })),
}));
doc.push(Caption("Figure 3.1  System architecture: the plan becomes the contract"));
doc.push(table(
  ["Layer", "Owns", "Does not own"],
  [
    ["Planner (Lab 1)", "Requirement slots, conflict detection, the locked plan and its revisions", "Any data access; it reads a scope register, not figures"],
    ["Graph (Lab 7)", "Which stage runs next, branch conditions, the repair cycle, escalation exits", "How a stage executes, or what it costs"],
    ["Runtime (Lab 6)", "Budgets, audit, checkpoints, approval gates, replay on resume", "The order of stages"],
    ["Connector (Lab 5)", "Resource definitions, scope checks, backend selection", "What the data means"],
    ["Stages (Labs 2–4, 8–13)", "One unit of work each, returning a headline and a detail record", "Control flow, budget or persistence"],
    ["Presentation", "Layout, status colours, tables and narration", "Any computation or judgement"],
  ],
  [22, 44, 34]));
doc.push(Caption("Table 3.1  Responsibilities of each architectural layer"));

doc.push(H2("3.2  Design Principles"));

doc.push(H3("3.2.1  Design principle 1: refusal is a first-class outcome"));
doc.push(P(
  "Most pipelines treat failure as an exception to be handled on the way to a " +
  "result. This system treats several kinds of refusal as legitimate terminal " +
  "outcomes, and expresses them structurally rather than as error handling."));
doc.push(P(
  "There are four escalation edges in the execution graph, each reached by a " +
  "named condition. The connector refuses a period for which no authorised " +
  "export exists, and the graph takes a no-data edge after three stages rather " +
  "than substituting a different period. Self-repair that exhausts its attempt " +
  "budget takes an unrepairable edge. An acceptance suite that is not fully " +
  "green takes a red edge. A rejection at the approval gate terminates without " +
  "publication. In every case the run stops, names the reason and publishes " +
  "nothing."));
doc.push(P(
  "A consequence worth stating is that this is testable. Because refusal is a " +
  "path through the graph rather than a thrown exception, each refusal is " +
  "asserted by the automated suite, and the system is verified to stop correctly " +
  "as rigorously as it is verified to succeed."));

doc.push(H3("3.2.2  Design principle 2: one door to data, with authorisation as data"));
doc.push(P(
  "Every figure in the system enters through a single connector. The connector " +
  "exposes typed resources, each declaring the parameters it accepts and the " +
  "scope a caller must hold, and the caller presents a token. Authorisation is " +
  "therefore data that can be inspected and varied, not a branch in code."));
doc.push(P(
  "This design yields two properties that would otherwise be difficult. First, " +
  "backend substitution: three interchangeable backends serve the resources — a " +
  "CSV file, a SQLite database and an HTTP-shaped API — and the calling agent " +
  "cannot determine which one responded, so connecting the system to a real " +
  "institutional ERP is the addition of a fourth backend rather than a rewrite. " +
  "Second, least privilege: the eight department agents hold a token with " +
  "exactly one scope, so a department agent is structurally incapable of reading " +
  "the institution-wide aggregate or the KPI register."));

// ======================= 4 IMPLEMENTATION =======================
doc.push(H1("4.  IMPLEMENTATION"));
doc.push(P(
  "This chapter describes how each layer was built. The implementation is shared " +
  "between fourteen lab notebooks and a reusable engine; both dashboards drive " +
  "the same engine code that the notebooks are assessed on, so the user " +
  "interface cannot demonstrate behaviour the labs do not have."));

doc.push(H2("4.1  The clarify loop and the plan-to-spec bridge"));
doc.push(P(
  "The planner maintains a goal object with six required slots: domains, " +
  "period, KPI set, target sets, drill-down policy and output type. A slot " +
  "extractor reads whatever the request already states, and the loop asks only " +
  "about what remains empty. The request 'Analyze our college performance' " +
  "fills none of the six, so six questions are generated; after one round of " +
  "answers, three remain; a fully specified request produces none at all."));
doc.push(P(
  "The questions themselves are composed from two observations rather than " +
  "looked up from a fixed list. If the request already names a domain, the " +
  "question about drill-down refers to that domain by name, and the question " +
  "about domains asks whether to widen rather than asking from scratch. The " +
  "options offered for the reporting period are read from the data-scope " +
  "register, so the system offers the periods it can actually serve. Each option " +
  "is also verified to be readable back by the extractor, which is asserted by " +
  "the test suite: an option the extractor cannot parse would be a control that " +
  "silently does nothing."));
doc.push(P(
  "Before locking the plan the agent reads a data-scope register and detects " +
  "conflicts between what was requested and what can be served. These conflicts " +
  "are carried into the brief as assumptions rather than silently resolved."));
doc.push(P(
  "The bridge from plan to specification is the join that makes the run agentic. " +
  "It reads the plan body rather than the original request, so a later revision " +
  "that patches the plan genuinely re-scopes the next run. The specification " +
  "names the required KPIs, the period, the domains, the drill-down policy and " +
  "the brief sections, and every later stage obeys it."));

doc.push(H2("4.2  Typed tools and the reusable skill"));
doc.push(P(
  "All computation passes through a tool router that validates each call " +
  "against a declared JSON schema before executing it: required arguments must " +
  "be present, types must match, and enumerated values must be in range. The " +
  "router records every call with its reason, inputs, outputs and duration, " +
  "producing a trace of 31 tool calls in a four-domain run."));
doc.push(P(
  "KPI computation is ordinary Python. Each definition declares a method — " +
  "ratio, weighted mean or sum — together with its numerator, denominator, " +
  "scale, unit, target, target source and system of record. Comparison against " +
  "target is a separate function returning variance, percentage of target, " +
  "status and, when applicable, a rounding warning. That warning is what " +
  "catches the 91.85 per cent case described in Chapter 1."));
doc.push(P(
  "The skill layer provides one registered skill, a domain review, with a " +
  "declared contract over its inputs and outputs. It is invoked once per domain " +
  "in scope — four times in the full run, once when the scope is narrowed to " +
  "Placement — which demonstrates reuse rather than four near-identical " +
  "implementations."));

doc.push(H2("4.3  Memory, retrieval and the governed connector"));
doc.push(P(
  "Memory is deliberately two stores with different lifetimes. A run state " +
  "object holds the draft and scratch values for the current run and is " +
  "discarded at the end. An archive holds published briefs and closed-year KPI " +
  "snapshots and is append-only: writing to an existing record identifier raises " +
  "rather than overwriting, so history cannot be rewritten."));
doc.push(P(
  "Retrieval over the archive is implemented directly rather than imported. A " +
  "similarity index tokenises each record, computes inverse document frequency, " +
  "builds TF-IDF vectors and ranks candidates by cosine similarity. A recall " +
  "stage runs before any data is read, returning two baseline snapshots and the " +
  "nearest prior decision brief at a similarity of 0.543, so the brief does not " +
  "re-propose an action already tried."));
doc.push(P(
  "The connector is an MCP-style server. It exposes four resources, each with " +
  "typed parameters and a required scope, and it issues tokens carrying scope " +
  "lists. The call path validates the token, checks the scope, verifies required " +
  "parameters, dispatches to the backend and logs the call with its holder, " +
  "duration and outcome."));
doc.push(table(
  ["Resource", "Required scope", "Backend"],
  [
    ["department_reports", "read:departments", "file:csv"],
    ["department_detail", "read:department-detail", "file:csv-detail"],
    ["kpi_definitions", "read:kpi-register", "sqlite"],
    ["external_benchmark", "read:benchmarks", "http:benchmark-api"],
  ],
  [34, 34, 32]));
doc.push(Caption("Table 4.1  Resources exposed by the MCP connector"));

doc.push(H2("4.4  The runtime and the execution graph"));
doc.push(P(
  "The runtime is the single entry point for executing a unit of work. Before " +
  "an action runs it checks whether the action has already completed, in which " +
  "case the stored result is returned without re-execution; it verifies " +
  "dependencies; it checks the budget for actions, connector calls and elapsed " +
  "seconds; and it raises if the action requires an approval that has not been " +
  "recorded. After execution it stores the result, appends an audit entry and " +
  "writes a checkpoint. A failure also checkpoints before propagating, so a " +
  "crash leaves a resumable state."));
doc.push(P(
  "The connector budget is measured as the growth of the connector's own call " +
  "log rather than as a counter the runtime increments. This matters because the " +
  "department agents call the connector directly: their seven calls are counted " +
  "against the run's budget automatically, and the reported figure of eight " +
  "connector calls is the truth rather than a self-report."));
doc.push(P(
  "The graph expresses the pipeline as eighteen nodes and twenty-one edges with " +
  "one back-edge for the repair cycle and four edges terminating at the " +
  "escalation exit. It is validated for reachability before any stage executes. " +
  "A second static check was added after a defect was found during development: " +
  "because an unconditional edge matches every condition, a node that mixes " +
  "conditional and unconditional out-edges silently shadows its conditional " +
  "branches. The check rejects such a node, along with duplicate condition " +
  "labels and branching without a router."));

doc.push(H2("4.5  The parallel department swarm"));
doc.push(P(
  "Eight department agents are dispatched concurrently through a thread pool " +
  "with bounded retries. Each agent holds the single-scope department token and " +
  "fetches its own department's fact rows through the connector, then rolls them " +
  "up by the aggregation rule carried in the data itself. An agent therefore " +
  "owns no data; it owns a token and a roll-up."));
doc.push(P(
  "Two faults are injected deliberately. One department's reporting system is " +
  "permanently unreachable, and another times out on its first attempt and " +
  "succeeds on retry. The run proceeds with seven of eight agents reporting, " +
  "and coverage of 87.5 per cent travels with the result rather than being " +
  "silently absorbed."));
doc.push(P(
  "Reconciliation is where the design differs from a conventional consolidation. " +
  "Agents return publication identifiers rather than counts. Three papers are " +
  "jointly authored by two departments and therefore appear in both returns, so " +
  "the naive sum of 174 overstates output; the union of identifiers gives 171. " +
  "The contested identifiers are reported, not merely the corrected total."));

doc.push(H2("4.6  Grounding, validation and self-repair"));
doc.push(P(
  "Each KPI becomes a candidate claim. A research step attaches evidence " +
  "consisting of a source system, a locator and a value, and the claim is " +
  "accepted only if its source is on the authorised list. An ungrounded claim is " +
  "dropped rather than softened, and the number dropped is reported."));
doc.push(P(
  "Validation checks the assembled draft against six constraints derived from " +
  "the specification. A defect injected on purpose removes the source attribution " +
  "from one KPI, so validation fails on the constraint that every figure cites " +
  "its source. Diagnosis identifies the offending row and the repair restores " +
  "only that row: one of nine, with the other eight left byte-identical. The " +
  "graph then follows its back-edge to re-validate, which passes."));
doc.push(P(
  "When repair cannot succeed — in the configuration that injects a KPI with no " +
  "approved definition — the repair budget of three attempts is spent and the " +
  "run takes the unrepairable edge to escalation. Nothing is published and the " +
  "reason is recorded."));

doc.push(H2("4.7  The acceptance factory and governance"));
doc.push(P(
  "The acceptance suite is generated from the specification rather than written " +
  "in advance. Tests are derived for KPI coverage, domain scope, grounding, " +
  "figure status, option coverage and the drill-down policy. The four-domain " +
  "request with mandatory drill-down produces twenty-two tests; narrowing to " +
  "Placement produces fifteen. Submission to a human is the only path onward and " +
  "refuses anything that is not fully green."));
doc.push(P(
  "Governance enforces role-checked approval. Each actor carries a role with " +
  "rights to approve, roll back, see department detail and see provisional " +
  "figures. A reader without department rights receives a redacted view in which " +
  "the drill-down is replaced by a statement that detail is withheld. Approval " +
  "records the named human and any edits; publication assigns a version; " +
  "rollback is recorded as a new audit entry rather than as an edit to history."));

doc.push(H2("4.8  Domain specialists and integration"));
doc.push(P(
  "Four domain packs draft options for off-target KPIs, each validating its own " +
  "output against its domain's scheme — a title, an owner, a timeline, risks, a " +
  "trade-off and a measure of success. A pack that produces a malformed option " +
  "rejects it itself rather than relying on a downstream check."));
doc.push(P(
  "The integration layer adds no capability. Its one substantive act is to " +
  "reconcile a naming difference: the acceptance suite looks for a field named " +
  "drilldown while the redaction layer looks for one named departments. Rather " +
  "than editing either lab, integration supplies both names from one computation " +
  "— which is the kind of mismatch that only appears when independently " +
  "developed components are composed."));

doc.push(H2("4.9  The dataset"));
doc.push(P(
  "The dataset is synthetic, static and generated by the project. Eight " +
  "department files hold 624 rows in long form — one row per department, period, " +
  "domain, metric and sub-period — covering two academic years and all four " +
  "domains, alongside an eight-row institution-wide aggregate and a SQLite KPI " +
  "register."));
doc.push(P(
  "Granularity follows the metric rather than being uniform: examinations are " +
  "recorded per semester, research and expenditure per quarter, and headcounts " +
  "annually. Every row carries its own aggregation rule — sum, weighted mean or " +
  "latest — so a consumer cannot roll a mean up as though it were a total."));
doc.push(table(
  ["Domain", "Metrics", "Grain", "Aggregation"],
  [
    ["Academic", "students appeared, students passed", "semester", "sum"],
    ["Academic", "CO/PO attainment", "annual", "weighted mean"],
    ["Research", "publications, citations, grants", "quarter", "sum"],
    ["Research", "sanctioned faculty", "annual", "latest"],
    ["Placement", "placed students, package, interns completed", "quarter", "sum"],
    ["Placement", "eligible students", "annual", "latest"],
    ["Finance", "budget allocated, budget spent", "quarter", "sum"],
  ],
  [14, 44, 18, 24]));
doc.push(Caption("Table 4.2  Metrics in the department fact tables"));
doc.push(P(
  "The generator refuses to write any file unless two invariants hold: the " +
  "current-year detail rolls up exactly to the published institution-wide " +
  "aggregate, and the prior-year detail reproduces all nine KPI values held in " +
  "the archive as the closed-year snapshot. The detail is therefore a " +
  "decomposition of the published figures rather than a second set of numbers " +
  "that disagrees with them."));
doc.push(P(
  "Satisfying the second invariant required one deliberate choice. Students are " +
  "whole people, and 73.50 per cent of the current eligible pool of 1,037 is not " +
  "an integer; the nearest achievable rates are 73.48 and 73.53. A prior-year " +
  "pool of 1,000 is the only size nearby that reproduces both archived placement " +
  "rates exactly, and a pool that grew by roughly four per cent in a year is " +
  "unremarkable. The alternative was to let the detail disagree with the archive " +
  "by a few hundredths, which is precisely the drift the grounding layer exists " +
  "to prevent."));

// ======================= 5 RESULTS AND DISCUSSIONS =======================
doc.push(H1("5.  RESULTS AND DISCUSSIONS"));
doc.push(P(
  "Every figure in this chapter is produced by executing the system; none is " +
  "quoted from design intent. The run used throughout is a fully specified " +
  "request covering all four domains for academic year 2025-26 with mandatory " +
  "department-level drill-down, executed with the repairable-defect condition " +
  "enabled."));

doc.push(H2("5.1  Expectations and how they were met"));
doc.push(P(
  "Table 5.1 is the central result of this report. Each row is a laboratory " +
  "exercise, its stated acceptance criterion, the mechanism built to satisfy it " +
  "and the observable evidence that it is satisfied."));
doc.push(table(
  ["Lab", "Expectation", "How it was met", "Evidence"],
  [
    ["1", "The agent clarifies rather than assuming, and locks an explicit plan", "Six-slot goal, question generation from the request and the register, conflict detection before locking", "6 questions → 3 → plan r0; 3 conflicts carried as assumptions"],
    ["2", "Every figure comes from a checked tool call", "Schema-validating router; KPI maths in Python; target comparison with rounding detection", "9 KPIs computed, 31 routed calls, 3 rounding flags"],
    ["3", "One reusable skill, used by the agent", "Registered skill with a declared contract, invoked per domain in scope", "1 skill across 4 domains"],
    ["4", "Recall before, archive after; archive is append-only", "RunState for the run, Archive for history, TF-IDF + cosine retrieval", "2 snapshots recalled, nearest brief at 0.543; archive refuses overwrite"],
    ["5", "Servers or tools connected and working", "MCP server, 4 typed resources, 3 interchangeable backends, scoped tokens", "8 rows served; intern token refused with FORBIDDEN_SCOPE"],
    ["6", "Every action logged; a crashed run resumes from its checkpoint", "Runtime with budgets, audit, checkpoint-after-each-action and approval gates", "35 audit entries; 15 stages replayed, 0 re-executed, slowest 0.010 ms"],
    ["7", "Stage order and branches are an explicit, validated graph", "18 nodes, 21 edges, one back-edge, four escalation edges; reachability and mixed-edge checks", "33 graph steps walked; the repair cycle is a real back-edge"],
    ["8", "Agents coordinate with clear roles", "Thread pool, one agent per department, each with a single-scope token", "7/8 succeeded in 261 ms vs 829 ms serial (3.2x); 273 fact rows via 7 connector calls"],
    ["9", "Every claim maps to an in-scope source", "Candidate-evidence model with source, locator and value; unsourced claims dropped", "9/9 claims grounded, 0 dropped"],
    ["10", "Failures are diagnosed and repaired, or escalated", "Constraint validation, minimal repair, back-edge re-validation, bounded attempts", "1 of 9 rows repaired in 1 attempt; all 6 constraints satisfied on pass 2"],
    ["11", "No artifact advances without a fully passing report", "Suite derived from the specification; submission refuses anything not green", "22/22 tests green before the human was asked"],
    ["12", "Role-checked approval, versioning, rollback, audit", "Actor roles, redaction by access level, versioned releases, rollback as a new entry", "v1 published by a named approver; Council member refused by name"],
    ["13", "Domain packs draft usable options", "Four specialists validating output against their own schema", "9 options drafted, 0 rejected by their own check"],
    ["14", "Integration adds wiring, not capability", "Capstone composes existing layers; reconciles the drilldown/departments naming mismatch", "19-stage run assembled from unmodified lab components"],
  ],
  [7, 23, 35, 35]));
doc.push(Caption("Table 5.1  Course expectations, per lab, and how each was met"));

doc.push(H2("5.2  End-to-end run: one request to an approved brief"));
doc.push(P(
  "Table 5.2 records the stages of a complete run in execution order. Stages 1 " +
  "to 16 execute unattended; the run then stops at the approval gate. After " +
  "approval the graph is walked a second time, during which the fifteen " +
  "completed stages are replayed from the checkpoint and only the remaining " +
  "three execute."));
doc.push(table(
  ["#", "Lab", "Stage", "ms", "Result"],
  [
    ["1", "1", "Locked plan accepted", "0.8", "plan r0 locked; 10 steps; 9 KPIs in scope"],
    ["2", "4", "Recall prior context", "2.8", "2 snapshots; nearest prior brief at 0.543"],
    ["3", "5", "Read through the connector", "0.5", "8 department rows, coordinator scope"],
    ["4", "8", "Department agents, parallel", "261.0", "7/8 succeeded; serial 829 ms (3.2x); CIVIL failed"],
    ["5", "8", "Reconcile conflicting claims", "0.7", "coverage 87.5%; 174 claimed → 171 reconciled"],
    ["6", "3", "Reusable skill per domain", "11.3", "1 skill, 4 domains, 31 routed tool calls"],
    ["7", "2", "Typed tools compute KPIs", "1.4", "9 computed; 1 provisional; 3 rounding flags"],
    ["8", "13", "Specialists draft options", "2.1", "9 options by 4 packs; 0 self-rejected"],
    ["9", "14", "Compose the draft", "2.9", "9 KPIs, 9 options, 7 sections, status DRAFT"],
    ["10", "9", "Ground every claim", "12.2", "9/9 grounded; 0 dropped"],
    ["11", "10", "Validate", "4.0", "FAILED: every-figure-cites-its-source at KPI-R2"],
    ["12", "10", "Diagnose and repair", "7.4", "repaired in 1 attempt; 1 of 9 rows touched"],
    ["13", "10", "Validate (pass 2)", "1.3", "all 6 constraints satisfied"],
    ["14", "11", "Acceptance suite", "1.9", "22/22 derived tests green"],
    ["15", "11", "Gate: route to a human", "1.3", "submitted with 22 green tests"],
    ["16", "12", "Approval (role-checked)", "0.0", "PAUSED — waiting for a named human"],
    ["17", "12", "Approval, after signature", "3.9", "approved by Dr. A. Principal"],
    ["18", "12", "Publish, version, audit", "13.7", "published v1; rollback available"],
    ["19", "4", "Archive, append-only", "2.0", "archived; archive now holds 7 records"],
  ],
  [5, 6, 30, 8, 51]));
doc.push(Caption("Table 5.2  Stage-by-stage trace of one complete run"));
doc.push(P(
  "Total agent time is 331 ms across nineteen stages, excluding presentation " +
  "pacing and the time the approver takes. The budget consumed is eighteen of " +
  "forty permitted actions and eight connector calls, of which seven were made " +
  "by the department agents and one by the coordinator."));
doc.push(...figure("fig2_run.jpg", "Figure 5.2  A run in progress, narrating the stage it is executing"));

doc.push(H2("5.3  The brief the run produced"));
doc.push(P(
  "Table 5.3 is the published scorecard. Two KPIs are at risk and six are below " +
  "target; one figure is provisional and carries that status on the face of the " +
  "brief."));
doc.push(table(
  ["KPI", "Value", "Target", "Status", "Source system"],
  [
    ["Institution pass percentage", "91.85 %", "92.0", "at risk", "Academic ERP"],
    ["CO/PO attainment index", "2.48", "2.5", "at risk", "Academic ERP (OBE module)"],
    ["Publications per faculty", "1.19", "1.5", "below target", "Research repository"],
    ["Citations per faculty", "7.26", "9.0", "below target", "Research repository"],
    ["Grants sanctioned", "242.50 lakh", "300.0", "below target", "Research repository"],
    ["Placement percentage", "75.12 %", "80.0", "below target", "Placement Cell tracker"],
    ["Average package", "7.67 LPA", "8.0", "below target", "Placement Cell tracker"],
    ["Internship completion", "73.38 %", "85.0", "below target", "Placement Cell tracker"],
    ["Budget utilisation (provisional)", "86.96 %", "90.0", "below target", "Finance & Accounts"],
  ],
  [30, 14, 12, 16, 28]));
doc.push(Caption("Table 5.3  KPI scorecard produced by the run"));
doc.push(P(
  "The pass percentage illustrates the rounding problem directly. At 91.85 " +
  "against a target of 92.0 the KPI is missed, but rounded to one decimal place " +
  "it reads as 92.0 and appears to meet the target. The system attaches an " +
  "explicit warning and reports the unrounded figure."));
doc.push(...figure("fig3_board.jpg", "Figure 5.3  The published KPI scorecard"));

doc.push(H2("5.4  Department-level results"));
doc.push(P(
  "Every KPI carries a department breakdown in which each department is judged " +
  "against the same target by the same comparison function used for the " +
  "institution figure, so a status means the same thing at both levels. Table " +
  "5.4 shows placement percentage."));
doc.push(table(
  ["Department", "Value", "Variance", "Status"],
  [
    ["Biotechnology", "50.88 %", "-29.12", "below target"],
    ["Civil Engineering", "52.54 %", "-27.46", "below target"],
    ["Chemical Engineering", "56.90 %", "-23.10", "below target"],
    ["Mechanical Engineering", "63.79 %", "-16.21", "below target"],
    ["Electrical & Electronics", "74.14 %", "-5.86", "below target"],
    ["Electronics & Communication", "83.14 %", "+3.14", "on target"],
    ["Information Science", "90.35 %", "+10.35", "on target"],
    ["Computer Science", "92.98 %", "+12.98", "on target"],
  ],
  [40, 20, 20, 20]));
doc.push(Caption("Table 5.4  Department breakdown for placement percentage"));
doc.push(P(
  "The institution-wide figure of 75.12 per cent conceals a 42-point spread. " +
  "Five of eight departments are below target and three are above it, and the " +
  "brief names them rather than reporting an average. This is the result that " +
  "most directly serves the SDG framing in Section 1.1, and it is the one a " +
  "conventional consolidated report destroys."));
doc.push(...figure("fig4_dept.jpg", "Figure 5.4  Department-level drill-down for placement percentage"));

doc.push(H2("5.5  The run changes with the request"));
doc.push(P(
  "To test whether the plan genuinely governs execution, the same system was " +
  "driven with five different requests and the resulting runs compared. Table " +
  "5.5 records the result."));
doc.push(table(
  ["Request / answers", "Questions", "Domains", "KPIs", "Tests", "Stages", "Packs", "Outcome"],
  [
    ["All four domains", "6→3→0", "4", "9", "21", "18", "4", "published v1"],
    ["Placement only", "6→3→0", "1", "3", "15", "16", "1", "published v1"],
    ["Research and Finance", "6→3→0", "2", "4", "16", "18", "2", "published v1"],
    ["Fully specified in the request", "0", "4", "9", "22", "18", "4", "published v1"],
    ["Period 2019-20", "6→3→0", "4", "9", "—", "3", "0", "escalated"],
  ],
  [28, 12, 10, 8, 9, 10, 9, 14]));
doc.push(Caption("Table 5.5  How the run changes with the request"));
doc.push(P(
  "No column in that table is constant. The acceptance suite is generated, not " +
  "stored: twenty-one, fifteen, sixteen and twenty-two tests for four different " +
  "specifications, the last being larger than the first because mandatory " +
  "drill-down derives an additional test. The number of domain packs invoked " +
  "follows the scope. The final row takes a different path through the graph " +
  "entirely: the connector has no authorised export for 2019-20, so the run " +
  "terminates after three stages with nothing computed and nothing published."));
doc.push(P(
  "Revision was tested the same way. Feedback of 'show me department-wise " +
  "placement results only' on a published four-domain brief patches the plan " +
  "with three domain removals and one policy change, taking the next run from " +
  "nine KPIs and twenty-one tests to three KPIs and sixteen, with every " +
  "published KPI carrying all eight departments. Six plan fields changed and " +
  "five were provably untouched, which is a patch rather than a regeneration."));

doc.push(H2("5.6  Refusal paths"));
doc.push(P(
  "Four refusal paths were executed and verified. In each case the system " +
  "stopped, named the reason, and published nothing."));
doc.push(table(
  ["Condition", "Where it stops", "Observed outcome"],
  [
    ["A KPI loses its source attribution", "Lab 10, repairable", "Repaired 1 row of 9 in one attempt, re-validated, run continues"],
    ["A KPI row with no approved definition", "Lab 10, unrepairable", "Repair budget of 3 attempts spent; escalates; acceptance never reached"],
    ["Reviewer lacks approval rights", "Lab 12 gate", "Refused by name; no version created"],
    ["Reviewer rejects the brief", "Lab 12 gate", "Escalated; governed store remains empty; rejection audited"],
    ["Period has no authorised export", "Lab 5 connector", "No-data edge taken after 3 stages; period substitution refused"],
  ],
  [30, 22, 48]));
doc.push(Caption("Table 5.6  Refusal paths and their outcomes"));

doc.push(H2("5.7  Verification"));
doc.push(P(
  "The system is verified by 284 automated checks that require no browser. The " +
  "Streamlit testing harness drives the real user interface headlessly, so the " +
  "tests exercise the same code path a human does."));
doc.push(table(
  ["Suite", "Checks", "What it covers"],
  [
    ["Lab acceptance (14 notebooks)", "186", "Each lab's own stated acceptance criterion"],
    ["Lab-by-lab dashboard", "included", "All 14 tabs driving the graded code"],
    ["End-to-end pipeline interface", "98", "Clarify, run, approve, revise, roll back and every refusal path"],
    ["Total", "284", "Executed in roughly 90 seconds on a laptop"],
  ],
  [34, 14, 52]));
doc.push(Caption("Table 5.7  Automated verification coverage"));
doc.push(P(
  "The pipeline suite is written to prove refusal as rigorously as success. It " +
  "asserts that a rejection publishes nothing, that a role without approval " +
  "rights is refused by name, that an unrepairable defect never reaches the " +
  "acceptance suite, that a period with no export is refused at the connector, " +
  "that a replayed stage completes in under a millisecond, and that clicking the " +
  "clarifying options without typing anything is sufficient to drive a complete " +
  "run."));

doc.push(H2("5.8  Ideas tested and rejected"));
doc.push(P(
  "Several approaches were implemented and then abandoned. They are recorded " +
  "because the reasons shaped the final design."));
doc.push(Bullet(
  "Deriving scope from the original request rather than the plan. The first " +
  "implementation of the plan-to-specification bridge read the goal object. " +
  "Revision then appeared to work — the plan changed — while the next run " +
  "produced identical output, because the goal still held what was first asked. " +
  "The bridge now reads the plan, which is the only artifact a revision mutates."));
doc.push(Bullet(
  "Allowing unconditional and conditional edges from the same graph node. " +
  "Because an unconditional edge matches every condition, the escalation " +
  "branches were unreachable while appearing correct in the diagram. All " +
  "branching edges are now conditional and a static check enforces it."));
doc.push(Bullet(
  "Reporting wall-clock time as the run's cost. The first implementation " +
  "included presentation pacing and the human's time at the approval gate, " +
  "producing a figure of 1,431 ms that measured the demonstration rather than " +
  "the system. Agent time is now summed across stages and reported separately " +
  "from elapsed time."));
doc.push(Bullet(
  "A seconds-resolution suffix for archive record identifiers. Two runs " +
  "completing within the same second collided, and the append-only archive " +
  "correctly refused the second write — crashing the application. The identifier " +
  "now increments until it is free."));
doc.push(Bullet(
  "Offering clarifying options whose text the slot extractor could not read " +
  "back. Two such options existed and were silently inert when clicked. Every " +
  "option is now asserted to fill its own slot."));

doc.push(H2("5.9  Discussion"));
doc.push(P(
  "The results support the two design principles stated in Chapter 1. Making " +
  "the plan the operative contract is what produces the variation in Table 5.5; " +
  "had the specification been fixed, those five requests would have produced " +
  "five identical runs. Separating control flow from execution is what produces " +
  "the replay result: fifteen stages recovered in under a millisecond each, " +
  "because the runtime recognises completed actions regardless of why the run " +
  "stopped."));
doc.push(P(
  "The most instructive outcome concerns demonstration rather than capability. " +
  "In peer evaluation the system scored full marks on the agent loop, skills and " +
  "the swarm, but lost marks on the runtime — the layer with the strongest " +
  "implementation. The reason was that the runtime's controls were never shown " +
  "refusing anything; budgets, gates and checkpoint-resume are invisible when a " +
  "run succeeds. A capability that cannot be observed failing is indistinguishable " +
  "from a capability that was never built, and the correct response is to " +
  "demonstrate the refusal, not to describe the code."));
doc.push(P(
  "A second observation concerns determinism. There is no model inference in the " +
  "execution path of the dashboard, which makes the run byte-reproducible and " +
  "allows 284 tests to assert fixed values. The cost is that the natural-language " +
  "understanding is pattern-based rather than semantic. The appropriate claim is " +
  "therefore precise: the agentic behaviour resides in the loop, the branching " +
  "and the refusals, not in a language model, and the system is stronger for " +
  "being honest about where the intelligence is."));

// ======================= 6 CONCLUSION =======================
doc.push(H1("6.  CONCLUSION AND FUTURE SCOPE OF THE WORK"));
doc.push(P(
  "This worklet set out to turn a free-text request from institutional " +
  "leadership into an approved, versioned and reversible decision brief without " +
  "a human assembling it by hand, and to do so in a way where every figure can " +
  "be traced to the system it came from. The resulting pipeline executes " +
  "nineteen stages in 331 ms of agent time, dispatches eight department agents " +
  "in parallel, reconciles conflicting departmental claims by identity, repairs " +
  "a defective row without disturbing correct ones, derives and passes " +
  "twenty-two acceptance tests generated from the request itself, and stops at a " +
  "role-checked gate. All sixteen functional requirements in Chapter 2 are met, " +
  "and the mechanism and evidence for each are recorded in Table 5.1."));
doc.push(P(
  "The property we consider most important is the one hardest to demonstrate: " +
  "the system refuses. It refuses a vague request, a period it has no " +
  "authorisation for, a claim without a source, an artifact with a red test, and " +
  "a reviewer without approval rights. Each refusal is a path through a validated " +
  "graph and each is asserted by the automated suite, so the system is verified " +
  "to stop correctly as rigorously as it is verified to succeed."));
doc.push(P("Four directions follow directly from the limitations recorded in this report."));
doc.push(Bullet(
  "Cloud build, test and deployment. Build and test are currently local. " +
  "Continuous integration running both suites on every push, and a hosted " +
  "deployment of the pipeline interface, would complete the SDLC expectation."));
doc.push(Bullet(
  "Durable memory across restarts. The archive is in-process, so published " +
  "briefs do not survive a restart. Persisting it, and reading checkpoints at " +
  "launch rather than only within a session, would make the recall loop true " +
  "across sessions."));
doc.push(Bullet(
  "Year-on-year movement in the brief. The prior-year detail already exists and " +
  "reproduces the archived baseline exactly, but the brief does not yet report " +
  "direction. Reporting that a KPI improved while still missing its target is a " +
  "different decision from reporting that it declined."));
doc.push(Bullet(
  "An out-of-process connector and a real source system. The connector is " +
  "in-process. Exposing it over a standard transport, and adding a backend for " +
  "an institutional ERP, would exercise the backend-substitution property the " +
  "design was built for."));

// ======================= REFERENCES =======================
doc.push(H1("REFERENCES"));
const refs = [
  "Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., and Cao, Y., " +
  "“ReAct: Synergizing Reasoning and Acting in Language Models,” International " +
  "Conference on Learning Representations, 2023.",
  "Anthropic, “Model Context Protocol Specification,” 2024. Available: " +
  "https://modelcontextprotocol.io",
  "Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M., Zettlemoyer, " +
  "L., Cancedda, N., and Scialom, T., “Toolformer: Language Models Can Teach " +
  "Themselves to Use Tools,” Advances in Neural Information Processing Systems, 2023.",
  "LangChain, “LangGraph: Building Stateful, Multi-Actor Applications with LLMs,” " +
  "technical documentation, 2024.",
  "Wu, Q., Bansal, G., Zhang, J., Wu, Y., Li, B., Zhu, E., Jiang, L., Zhang, X., " +
  "Zhang, S., Awadallah, A., White, R. W., Burger, D., and Wang, C., “AutoGen: " +
  "Enabling Next-Gen LLM Applications via Multi-Agent Conversation,” 2023.",
  "Shinn, N., Cassano, F., Berman, E., Gopinath, A., Narasimhan, K., and Yao, S., " +
  "“Reflexion: Language Agents with Verbal Reinforcement Learning,” Advances in " +
  "Neural Information Processing Systems, 2023.",
  "Salton, G., and Buckley, C., “Term-Weighting Approaches in Automatic Text " +
  "Retrieval,” Information Processing and Management, vol. 24, no. 5, 1988.",
  "National Institutional Ranking Framework, “India Rankings: Methodology for " +
  "Engineering Institutions,” Ministry of Education, Government of India, 2024.",
  "National Assessment and Accreditation Council, “Manual for Self-Study Report: " +
  "Affiliated/Constituent Colleges,” University Grants Commission, 2023.",
  "Gartner, “Agentic AI: Architecture Patterns for Enterprise Decision Support,” " +
  "research note, 2024.",
  "Streamlit, “Application Testing Framework (streamlit.testing.v1),” technical " +
  "documentation, 2024.",
  "Google, “Gemini API: Function Calling and Structured Output,” developer " +
  "documentation, 2025.",
];
refs.forEach((r, i) => doc.push(new Paragraph({
  alignment: AlignmentType.JUSTIFIED,
  spacing: { after: 110, line: 264 },
  indent: { left: 420, hanging: 420 },
  children: [new TextRun({ text: `[${i + 1}]  ${r}`, size: 21, font: FONT })],
})));

// ======================= APPENDIX =======================
doc.push(H1("APPENDIX A"));
doc.push(H2("A.1  Screen shots"));
doc.push(P(
  "The following screens are taken from the end-to-end pipeline interface " +
  "during the run reported in Chapter 5."));
doc.push(...figure("fig0_brief.jpg",
  "Figure A.1  The only input the system requires to begin", 408));
doc.push(...figure("fig1_clarify.jpg",
  "Figure 5.1  The agent refuses a vague request and asks what it is missing"));
doc.push(P(
  "Each question offers answers that can be clicked and a box in which an " +
  "answer can be typed; both are read by the same extractor. The line beneath " +
  "each question states why the agent needs that requirement."));

doc.push(H2("A.2  Reproducing the results"));
doc.push(P("The repository is public and the results in Chapter 5 reproduce as follows."));
doc.push(Rich([{ t: "git clone https://github.com/NakulSingh156/Team-11-A-Div-Artifact-15.git", m: true }], { after: 40 }));
doc.push(Rich([{ t: "cd Team-11-A-Div-Artifact-15/dashboard && pip install -r requirements.txt", m: true }], { after: 40 }));
doc.push(Rich([{ t: "streamlit run pipeline_app.py      # the end-to-end pipeline", m: true }], { after: 40 }));
doc.push(Rich([{ t: "streamlit run app.py               # the lab-by-lab view, 14 tabs", m: true }], { after: 140 }));
doc.push(P("To execute the full verification suite:"));
doc.push(Rich([{ t: "python3 test_app.py && python3 test_pipeline_app.py", m: true }], { after: 140 }));
doc.push(P(
  "The run reported in Chapter 5 is reproduced by selecting the fully specified " +
  "example request, leaving the run condition at its default of a repairable " +
  "defect, and approving as Dr. A. Principal. No API key, network access or " +
  "database server is required; the dataset ships with the repository and is not " +
  "regenerated at import, so any edit made to it persists."));

// ---------------------------------------------------------------- document
const document = new Document({
  creator: "Team 11, A Division",
  title: "Worklet 15 — Executive Decision Support System",
  description: "Agentic AI (26ECAC401) final project report",
  numbering: {
    config: [{
      reference: "bullets",
      levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 520, hanging: 260 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "◦",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 900, hanging: 260 } } } },
      ],
    }],
  },
  styles: {
    default: {
      document: { run: { font: FONT, size: 22 } },
      heading1: { run: { font: FONT, size: 30, bold: true, color: "000000" },
                  paragraph: { spacing: { before: 240, after: 240 }, keepNext: true } },
      heading2: { run: { font: FONT, size: 25, bold: true, color: "000000" },
                  paragraph: { spacing: { before: 240, after: 120 }, keepNext: true } },
      heading3: { run: { font: FONT, size: 23, bold: true, color: "000000" },
                  paragraph: { spacing: { before: 180, after: 100 }, keepNext: true } },
    },
  },
  sections: [{
    properties: {
      page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } },
    },
    children: doc,
  }],
});

Packer.toBuffer(document).then(buf => {
  fs.writeFileSync(OUT, buf);
  console.log("written:", OUT, (buf.length / 1024).toFixed(0) + " KB");
});
