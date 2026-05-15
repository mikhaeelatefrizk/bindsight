// generate_cv.js - generates updated CV for Mikhaeel Atef Rizk
// Adds bindsight + 4 sister projects + ORCID + correct German level vs the previous PDF.
// Output: outreach/Mikhaeel-CV-2026-05-15.docx (gitignored)

const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, ExternalHyperlink,
  Header, Footer, AlignmentType, PageOrientation, LevelFormat,
  HeadingLevel, BorderStyle, AlignmentType: ALIGN,
  TabStopType, TabStopPosition, Table, TableRow, TableCell, WidthType, ShadingType,
} = require('docx');

const OUTPUT = path.resolve('C:/Users/mikha/Desktop/bioinformatics tool dev/outreach/Mikhaeel-CV-2026-05-15.docx');

// helpers ---------------------------------------------------------------------
const para = (children, opts = {}) => new Paragraph({ children, ...opts });
const run = (text, opts = {}) => new TextRun({ text, ...opts });
const bold = (text, opts = {}) => new TextRun({ text, bold: true, ...opts });
const heading1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  children: [new TextRun(text)],
});
const heading2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  children: [new TextRun(text)],
});
const link = (text, url) => new ExternalHyperlink({
  link: url,
  children: [new TextRun({ text, style: 'Hyperlink' })],
});
const hr = () => new Paragraph({
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: 'CCCCCC' } },
  spacing: { after: 80 },
});
const bullet = (children) => new Paragraph({
  numbering: { reference: 'bullets', level: 0 },
  spacing: { after: 60 },
  children,
});
const blank = () => new Paragraph({ children: [new TextRun('')] });

// content ---------------------------------------------------------------------

const sections = [];

// === HEADER ===
sections.push(new Paragraph({
  heading: HeadingLevel.TITLE,
  alignment: AlignmentType.CENTER,
  children: [new TextRun('Mikhaeel Atef Rizk Shehata')],
}));
sections.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  children: [new TextRun({ text: 'PharmD candidate · Bioinformatician · Open-source developer', italics: true, size: 22 })],
  spacing: { after: 200 },
}));

// === CONTACT ===
sections.push(heading1('Contact Information'));
sections.push(hr());
sections.push(bullet([bold('Email: '), run('mikhaeelatefrizk@proton.me')]));
sections.push(bullet([bold('Phone: '), run('+20 121 021 9945')]));
sections.push(bullet([bold('Location: '), run('Cairo, Egypt')]));
sections.push(bullet([bold('ORCID: '), link('0009-0006-1069-9558', 'https://orcid.org/0009-0006-1069-9558')]));
sections.push(bullet([bold('GitHub: '), link('github.com/mikhaeelatefrizk', 'https://github.com/mikhaeelatefrizk')]));
sections.push(bullet([bold('LinkedIn: '), link('linkedin.com/in/mikhaeel-shehata-6549b8378', 'https://linkedin.com/in/mikhaeel-shehata-6549b8378')]));
sections.push(blank());

// === PROFESSIONAL SUMMARY ===
sections.push(heading1('Professional Summary'));
sections.push(hr());
sections.push(para([
  run('PharmD candidate (German University in Cairo, expected June 2026, currently in clinical/Imtiyaz year) operating at the intersection of pharmacy, computational biology, and open-source software. Author and maintainer of '),
  bold('bindsight'),
  run(' — the first open-source RNA-seq → de novo protein binder pipeline (Zenodo DOI '),
  link('10.5281/zenodo.20121496', 'https://doi.org/10.5281/zenodo.20121496'),
  run(', JOSS submission and bioRxiv preprint both in review). Combines a rigorous pharmacy / drug-development background with a working bioinformatics portfolio (TCGA-KIRC survival analysis, Seurat single-cell scRNA-seq, RNA-seq DE replication, pre-registered systematic review). Multilingual (Arabic native; English fluent; German professional working proficiency). Open to immediate relocation post-Imtiyaz for a Master’s thesis at a German / DACH research institute.'),
]));
sections.push(blank());

// === CORE COMPETENCIES ===
sections.push(heading1('Core Competencies & Skills'));
sections.push(hr());

// Use simple heading + bulleted list pattern instead of table (more reliable across renderers)
sections.push(para([bold('Bioinformatics & open-source software')]));
sections.push(bullet([run('Open-source pipeline development end-to-end (bindsight: 24 commits, MIT, JOSS-style packaging, JSON-Schema-validated outputs)')]));
sections.push(bullet([run('RNA-seq differential expression (PyDESeq2, DESeq2-aware), single-cell RNA-seq (Seurat v5)')]));
sections.push(bullet([run('Protein structure / design ecosystem (RFdiffusion, ProteinMPNN, Boltz-2, AlphaFoldDB, SURFY, SURFACE-Bind)')]));
sections.push(bullet([run('Provenance & reproducibility (W3C PROV-O JSON-LD, RO-Crate export, CITATION.cff, Snakemake)')]));
sections.push(bullet([run('Streamlit web apps (deployed on Streamlit Cloud + Hugging Face Spaces)')]));
sections.push(blank());

sections.push(para([bold('Data & technology')]));
sections.push(bullet([run('Python (3.11+), R / RStudio, Git, GitHub Actions CI/CD, Docker basics')]));
sections.push(bullet([run('Clinical data analysis, statistical analysis, data visualization, predictive modelling')]));
sections.push(bullet([run('LIMS, CRM systems, Microsoft Office Suite (advanced)')]));
sections.push(blank());

sections.push(para([bold('Pharmaceutical & research')]));
sections.push(bullet([run('Pharmacoeconomics, drug formulation, clinical pharmacy, drug development')]));
sections.push(bullet([run('HPLC operation, microbiological culturing, aseptic techniques, quality-control testing')]));
sections.push(bullet([run('GLP compliance, experimental design, scientific writing')]));
sections.push(blank());

sections.push(para([bold('Professional & leadership')]));
sections.push(bullet([run('Project management, team leadership, collaborative problem-solving')]));
sections.push(bullet([run('Technical writing, presentation skills, cross-cultural communication')]));
sections.push(bullet([run('Agile methodology, mentoring')]));
sections.push(blank());

// === LANGUAGES ===
sections.push(heading1('Languages'));
sections.push(hr());
sections.push(bullet([bold('Arabic: '), run('Native proficiency')]));
sections.push(bullet([bold('English: '), run('Full professional proficiency')]));
sections.push(bullet([bold('German: '), run('Professional working proficiency (~B2)')]));
sections.push(bullet([bold('French: '), run('Limited working proficiency')]));
sections.push(bullet([bold('Russian: '), run('Elementary proficiency')]));
sections.push(blank());

// === EDUCATION ===
sections.push(heading1('Education'));
sections.push(hr());

sections.push(para([bold('Doctor of Pharmacy (PharmD), Pharmacy and Biotechnology')]));
sections.push(para([
  run('The German University in Cairo (GUC) · Cairo, Egypt · '),
  bold('October 2020 – June 2026 (expected graduation)'),
]));
sections.push(bullet([run('Currently in the clinical / Imtiyaz year')]));
sections.push(bullet([run('Maintaining exceptional academic performance with consistent outstanding grades')]));
sections.push(bullet([bold('Relevant coursework: '), run('Pharmacology, Pharmaceutical Chemistry, Pharmacoeconomics, Clinical Pharmacy, Pharmaceutical Microbiology, Biotechnology, Pharmaceutical Analysis, Drug Development')]));
sections.push(bullet([bold('Academic projects: '), run('Drug formulation optimization, Pharmacoeconomic modelling, Clinical case studies')]));
sections.push(bullet([bold('Professional development: '), run('Active member of the Pharmacy Student Association')]));
sections.push(blank());

sections.push(para([bold('General High School Diploma — American curriculum (STEM focus)')]));
sections.push(para([
  run('Saint John United Methodist Church · Cairo, Egypt · '),
  bold('June 2008 – June 2020'),
]));
sections.push(bullet([run('Participated in science fairs and academic competitions')]));
sections.push(bullet([run('Strong foundation in sciences preparing for pharmaceutical studies')]));
sections.push(blank());

// === PROJECTS & RESEARCH (with bindsight + sister projects) ===
sections.push(heading1('Projects & Research'));
sections.push(hr());

// bindsight — featured first
sections.push(para([bold('bindsight — open-source RNA-seq → de novo protein binder pipeline (lead author + maintainer)')]));
sections.push(para([
  bold('2026 · '),
  link('github.com/mikhaeelatefrizk/bindsight', 'https://github.com/mikhaeelatefrizk/bindsight'),
  run(' · Zenodo DOI '),
  link('10.5281/zenodo.20121496', 'https://doi.org/10.5281/zenodo.20121496'),
  run(' · v0.1.0 (MIT)'),
]));
sections.push(bullet([run('First open-source pipeline that takes RNA-seq counts and outputs ranked de novo protein binder candidates with full W3C PROV-O JSON-LD provenance and RO-Crate export')]));
sections.push(bullet([run('Discovery half: PyDESeq2 → SURFY → Open Targets → AlphaFoldDB → SURFACE-Bind, runs end-to-end on a CPU laptop in ~60 seconds')]));
sections.push(bullet([run('Design half: templates RFdiffusion + ProteinMPNN + Boltz-2 GPU jobs (Colab / Modal / Kaggle adapters)')]));
sections.push(bullet([run('Demo rediscovers HER2 (ERBB2) and EGFR — the textbook cancer immunotherapy targets — as the top antibody-tractable surface antigens, entirely from synthetic RNA-seq counts')]));
sections.push(bullet([run('Live demos: '), link('huggingface.co/spaces/Mikhaeelatefrizk/bindsight', 'https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight'), run(' (primary, 16 GB CPU, no auto-sleep) and '), link('bindsight.streamlit.app', 'https://bindsight.streamlit.app/'), run(' (mirror)')]));
sections.push(bullet([run('Submission status: JOSS submission and bioRxiv preprint both in review')]));
sections.push(blank());

// Sister projects
sections.push(para([bold('TCGA-KIRC survival analysis — EPAS1 / HIF-2α prognostic biomarker for kidney renal clear cell carcinoma')]));
sections.push(para([bold('2026 · '), link('github.com/mikhaeelatefrizk', 'https://github.com/mikhaeelatefrizk')]));
sections.push(bullet([run('Cox proportional hazards modelling on TCGA-KIRC RNA-seq data; identifies EPAS1 / HIF-2α as a prognostic biomarker (target of FDA-approved belzutifan)')]));
sections.push(blank());

sections.push(para([bold('Seurat v5 PBMC 3k single-cell RNA-seq workflow')]));
sections.push(para([bold('2026 · '), link('github.com/mikhaeelatefrizk', 'https://github.com/mikhaeelatefrizk')]));
sections.push(bullet([run('Standard 10x Genomics PBMC 3k pipeline: QC, normalization, integration, clustering, annotation; recovers 8 immune populations with full markers')]));
sections.push(blank());

sections.push(para([bold('Silver-Fox-domestication RNA-seq differential-expression replication')]));
sections.push(para([bold('2026 · '), link('github.com/mikhaeelatefrizk', 'https://github.com/mikhaeelatefrizk')]));
sections.push(bullet([run('Replicates the Kukekova et al. (PNAS 2018) differential-expression analysis on the Silver-Fox domestication dataset; demonstrates reproducibility of published RNA-seq DE pipelines')]));
sections.push(blank());

sections.push(para([bold('Pre-registered systematic review and meta-analysis (PROSPERO)')]));
sections.push(para([bold('2026 · '), link('github.com/mikhaeelatefrizk', 'https://github.com/mikhaeelatefrizk')]));
sections.push(bullet([run('PROSPERO-registered systematic review (k = 9), PRISMA 2020 reporting standard; demonstrates rigorous evidence-synthesis methodology')]));
sections.push(blank());

sections.push(para([bold('Arseniq — Pharmacy Management Software Prototype (Innovation Project Lead, Merck Group)')]));
sections.push(para([bold('August – September 2023')]));
sections.push(bullet([run('Led a 5-person cross-functional team to develop an innovative software prototype for pharmacy inventory management, product traceability, and accessibility')]));
sections.push(bullet([run('Projected 40% reduction in medication errors through real-time inventory tracking and integrated barcode scanning')]));
sections.push(bullet([run('Presented prototype to senior management; approved for further development')]));
sections.push(blank());

sections.push(para([bold('Pharmaceutical Microbiology Research (The German University in Cairo)')]));
sections.push(para([bold('2023')]));
sections.push(bullet([run('Investigated antimicrobial resistance patterns in clinical isolates and contributed to research on novel antimicrobial compounds; developed improved bacterial-identification protocols')]));
sections.push(blank());

// === PROFESSIONAL EXPERIENCE ===
sections.push(heading1('Professional Experience'));
sections.push(hr());

sections.push(para([bold('Clinical Data Analyst (Freelance / Independent)')]));
sections.push(para([bold('January 2024 – Present')]));
sections.push(bullet([run('Analyzed clinical trial data and healthcare datasets to identify trends and insights for improved patient outcomes')]));
sections.push(bullet([run('Developed data-visualization dashboards for healthcare stakeholders using advanced analytical tools')]));
sections.push(bullet([run('Conducted pharmacoeconomic analyses to support evidence-based healthcare decision-making')]));
sections.push(bullet([run('Applied AI and machine-learning techniques to predict treatment efficacy and optimize healthcare delivery')]));
sections.push(blank());

sections.push(para([bold('Customer Service Representative — Webhelp (Cairo, Egypt)')]));
sections.push(para([bold('August 2023 – October 2023 (3 months)')]));
sections.push(bullet([run('Achieved 95%+ customer-satisfaction ratings for international clients; recognized for the lowest complaint ratio in a team of 30+ representatives')]));
sections.push(bullet([run('Resolved complex technical and billing inquiries while managing 50+ daily customer interactions')]));
sections.push(blank());

sections.push(para([bold('Trainee — Innovation Project Lead — Merck Group (Cairo, Egypt)')]));
sections.push(para([bold('August 2023 – September 2023 (2 months)')]));
sections.push(bullet([run('Led a cross-functional team of 5 to develop the “Arseniq” pharmacy management software prototype')]));
sections.push(bullet([run('Applied agile methodology to deliver a functional prototype within a tight deadline')]));
sections.push(blank());

sections.push(para([bold('Customer Service Representative — Altice USA (Cairo, Egypt)')]));
sections.push(para([bold('July 2022 – October 2022 (4 months)')]));
sections.push(bullet([run('90%+ first-call-resolution rate handling high-volume technical and billing inquiries')]));
sections.push(bullet([run('Multilingual customer engagement; CRM-system tracking for service-improvement insights')]));
sections.push(blank());

sections.push(para([bold('Volunteer Junior Teaching Assistant — Pharmaceutical Microbiology Lab — The German University in Cairo')]));
sections.push(para([bold('February 2023 – June 2023 (5 months)')]));
sections.push(bullet([run('Assisted senior TAs in preparing and conducting laboratory experiments for 50+ students')]));
sections.push(bullet([run('Explained complex microbiological concepts using simplified teaching methods, resulting in 30% improvement in student comprehension')]));
sections.push(bullet([run('Managed laboratory safety protocols and ensured GLP compliance')]));
sections.push(blank());

sections.push(para([bold('Assistant Researcher — The German University in Cairo')]));
sections.push(para([bold('August 2021 – September 2021 (2 months)')]));
sections.push(bullet([run('Hands-on experience operating HPLC equipment for pharmaceutical analysis')]));
sections.push(bullet([run('Collaborated with senior researchers on pharmaceutical quality-control projects')]));
sections.push(blank());

// === CERTIFICATIONS ===
sections.push(heading1('Certifications & Professional Development'));
sections.push(hr());
sections.push(bullet([run('Good Laboratory Practice (GLP) Training')]));
sections.push(bullet([run('Customer Service Excellence Certification')]));
sections.push(bullet([run('HIPAA Compliance Basics')]));
sections.push(blank());

// === FOOTER NOTE ===
sections.push(para([
  new TextRun({ text: 'CV updated 2026-05-15 to reflect bindsight portfolio (4 sister projects) and ORCID. Source PDF: previous version.', italics: true, size: 18, color: '888888' }),
]));

// === BUILD DOC ===
const doc = new Document({
  styles: {
    default: { document: { run: { font: 'Calibri', size: 22 } } },
    paragraphStyles: [
      { id: 'Title', name: 'Title', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 40, bold: true, font: 'Calibri' },
        paragraph: { spacing: { before: 0, after: 120 }, alignment: AlignmentType.CENTER } },
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 28, bold: true, font: 'Calibri', color: '2E5984' },
        paragraph: { spacing: { before: 280, after: 60 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 24, bold: true, font: 'Calibri' },
        paragraph: { spacing: { before: 160, after: 60 }, outlineLevel: 1 } },
      { id: 'Hyperlink', name: 'Hyperlink', basedOn: 'Normal',
        run: { color: '0066CC', underline: { type: 'single' } } },
    ],
  },
  numbering: {
    config: [
      { reference: 'bullets',
        levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 }, // US Letter
        margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 }, // 0.75"
      },
    },
    children: sections,
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
  fs.writeFileSync(OUTPUT, buffer);
  console.log('Wrote ' + OUTPUT + ' (' + buffer.length + ' bytes)');
});
