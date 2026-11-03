"""
generate_submission_pdfs.py
Generates the 4 university-standard A4 PDFs for B.Tech CSE academic submission:
1. docs/final_submission/pdf/Final_Year_Project_Report.pdf
2. docs/final_submission/pdf/Algorithm_Explanations.pdf
3. docs/final_submission/pdf/Testing_Documentation.pdf
4. docs/final_submission/pdf/Viva_Preparation_Guide.pdf
"""

import os
import re
import base64
from pathlib import Path
import markdown
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "docs" / "final_submission"
PDF_DIR = DOCS_DIR / "pdf"
SCREENSHOTS_DIR = DOCS_DIR / "screenshots"

PDF_DIR.mkdir(parents=True, exist_ok=True)

# Common HTML template with KaTeX and Mermaid CDN
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <!-- Mermaid JS for SVG diagrams -->
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ 
            startOnLoad: true, 
            theme: 'neutral',
            themeVariables: {{
                primaryColor: '#e0e7ff',
                primaryTextColor: '#0f2b48',
                primaryBorderColor: '#2563eb',
                lineColor: '#0284c7',
                secondaryColor: '#f1f5f9',
                tertiaryColor: '#ffffff'
            }}
        }});
    </script>
    <!-- KaTeX for crisp LaTeX mathematics -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/contrib/auto-render.min.js"
        onload="renderMathInElement(document.body, {{
            delimiters: [
                {{left: '$$', right: '$$', display: true}},
                {{left: '$', right: '$', display: false}},
                {{left: '\\\\[', right: '\\\\]', display: true}},
                {{left: '\\\\(', right: '\\\\)', display: false}}
            ],
            throwOnError: false
        }});"></script>
    <style>
        @page {{
            size: A4;
            margin: 22mm 18mm 22mm 18mm;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: 10pt;
            line-height: 1.55;
            color: #1e293b;
            background-color: #ffffff;
            margin: 0;
            padding: 0;
        }}

        /* Headings */
        h1, h2, h3, h4, h5, h6 {{
            color: #0f2b48;
            font-weight: 700;
            margin-top: 1.4em;
            margin-bottom: 0.5em;
            page-break-after: avoid;
        }}

        h1 {{
            font-size: 20pt;
            border-bottom: 2.5px solid #2563eb;
            padding-bottom: 6px;
            margin-top: 0;
        }}

        h2 {{
            font-size: 14pt;
            border-bottom: 1px solid #cbd5e1;
            padding-bottom: 4px;
            color: #1e3a8a;
        }}

        h3 {{
            font-size: 11.5pt;
            color: #1d4ed8;
        }}

        h4 {{
            font-size: 10.5pt;
            color: #334155;
        }}

        p {{
            margin-top: 0;
            margin-bottom: 0.85em;
            text-align: justify;
        }}

        ul, ol {{
            margin-top: 0;
            margin-bottom: 0.85em;
            padding-left: 24px;
        }}

        li {{
            margin-bottom: 0.35em;
        }}

        /* Code & Pre */
        code {{
            font-family: "Consolas", "Courier New", monospace;
            font-size: 9pt;
            background-color: #f1f5f9;
            color: #0f2b48;
            padding: 2px 5px;
            border-radius: 3px;
            border: 1px solid #e2e8f0;
        }}

        pre {{
            background-color: #f8fafc;
            border: 1px solid #cbd5e1;
            border-radius: 5px;
            padding: 10px 14px;
            overflow-x: auto;
            font-family: "Consolas", "Courier New", monospace;
            font-size: 8.5pt;
            line-height: 1.45;
            page-break-inside: avoid;
        }}

        pre code {{
            background-color: transparent;
            padding: 0;
            border: none;
            color: #0f172a;
        }}

        /* Tables */
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 14px 0;
            font-size: 8.5pt;
            page-break-inside: avoid;
        }}

        th {{
            background-color: #0f2b48;
            color: #ffffff;
            font-weight: 600;
            text-align: left;
            padding: 7px 10px;
            border: 1px solid #0f2b48;
        }}

        td {{
            padding: 6px 10px;
            border: 1px solid #cbd5e1;
            vertical-align: top;
        }}

        tr:nth-child(even) td {{
            background-color: #f8fafc;
        }}

        /* Blockquotes / Callouts */
        blockquote {{
            margin: 12px 0;
            padding: 10px 16px;
            background-color: #eff6ff;
            border-left: 4.5px solid #2563eb;
            color: #1e3a8a;
            border-radius: 0 4px 4px 0;
            page-break-inside: avoid;
        }}

        blockquote p:last-child {{
            margin-bottom: 0;
        }}

        /* Badges */
        .badge {{
            display: inline-block;
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 7.5pt;
            font-weight: 700;
            text-transform: uppercase;
        }}

        .badge-pass {{
            background-color: #dcfce7;
            color: #15803d;
            border: 1px solid #86efac;
        }}

        .badge-fail {{
            background-color: #fee2e2;
            color: #b91c1c;
            border: 1px solid #fca5a5;
        }}

        /* Diagrams */
        .mermaid {{
            margin: 16px 0;
            text-align: center;
            background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            padding: 14px;
            border-radius: 6px;
            page-break-inside: avoid;
        }}

        /* Formal Title Page for Project Report */
        .title-page {{
            page-break-after: always;
            text-align: center;
            padding-top: 30px;
            padding-bottom: 30px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            min-height: 900px;
        }}

        .university-header {{
            font-size: 13pt;
            font-weight: 700;
            color: #0f2b48;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 6px;
        }}

        .department-header {{
            font-size: 11pt;
            font-weight: 600;
            color: #2563eb;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 40px;
        }}

        .project-title-box {{
            margin: 30px 0;
            padding: 24px 20px;
            border-top: 3px double #0f2b48;
            border-bottom: 3px double #0f2b48;
        }}

        .project-title {{
            font-size: 18pt;
            font-weight: 800;
            color: #0f2b48;
            line-height: 1.35;
            text-transform: uppercase;
            margin: 0;
        }}

        .project-subtitle {{
            font-size: 11pt;
            font-weight: 500;
            color: #475569;
            margin-top: 10px;
        }}

        .report-degree-text {{
            font-size: 10.5pt;
            color: #334155;
            line-height: 1.6;
            margin: 25px 0;
        }}

        .meta-table {{
            width: 100%;
            margin: 30px auto;
            border: none;
        }}

        .meta-table td {{
            border: none;
            background: transparent !important;
            padding: 6px 16px;
            font-size: 10pt;
        }}

        .meta-left {{
            text-align: left;
            width: 50%;
        }}

        .meta-right {{
            text-align: right;
            width: 50%;
        }}

        .academic-year {{
            font-size: 11pt;
            font-weight: 700;
            color: #0f2b48;
            margin-top: 30px;
        }}

        .page-break {{
            page-break-after: always;
        }}

        /* Certificate & Declaration */
        .certificate-box {{
            page-break-after: always;
            padding-top: 20px;
        }}

        .cert-title {{
            text-align: center;
            font-size: 16pt;
            font-weight: 700;
            color: #0f2b48;
            text-transform: uppercase;
            border-bottom: 2px solid #0f2b48;
            padding-bottom: 8px;
            margin-bottom: 30px;
        }}

        .signature-grid {{
            display: flex;
            justify-content: space-between;
            margin-top: 60px;
        }}

        .signature-block {{
            width: 30%;
            text-align: center;
            border-top: 1px dashed #64748b;
            padding-top: 8px;
            font-size: 9.5pt;
            font-weight: 600;
            color: #334155;
        }}

        /* Viva Q&A styling */
        .viva-card {{
            margin-bottom: 16px;
            border-radius: 6px;
            border: 1px solid #cbd5e1;
            overflow: hidden;
            page-break-inside: avoid;
        }}

        .viva-question {{
            background-color: #0f2b48;
            color: #ffffff;
            padding: 8px 14px;
            font-weight: 700;
            font-size: 10pt;
            display: flex;
            align-items: baseline;
        }}

        .viva-question-num {{
            background-color: #2563eb;
            color: #ffffff;
            padding: 2px 7px;
            border-radius: 4px;
            font-size: 8pt;
            margin-right: 10px;
            font-weight: 700;
        }}

        .viva-answer {{
            background-color: #f8fafc;
            padding: 12px 16px;
            font-size: 9.5pt;
            color: #1e293b;
            border-top: 1px solid #cbd5e1;
        }}

        /* Screenshot figure */
        .screenshot-card {{
            margin: 20px 0;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            overflow: hidden;
            background-color: #f8fafc;
            page-break-inside: avoid;
            text-align: center;
        }}

        .screenshot-img {{
            width: 100%;
            max-height: 480px;
            object-fit: contain;
            display: block;
            border-bottom: 1px solid #e2e8f0;
            background-color: #ffffff;
        }}

        .screenshot-caption {{
            padding: 10px 14px;
            font-size: 9pt;
            font-weight: 600;
            color: #0f2b48;
            text-align: center;
        }}

        .screenshot-desc {{
            padding: 0 14px 10px 14px;
            font-size: 8.5pt;
            color: #475569;
            text-align: justify;
        }}

        .disclaimer-banner {{
            background-color: #fffbeb;
            border: 1.5px solid #d97706;
            color: #92400e;
            padding: 12px 16px;
            border-radius: 6px;
            margin: 16px 0;
            page-break-inside: avoid;
        }}

        .disclaimer-banner strong {{
            color: #b45309;
        }}
    </style>
</head>
<body>
{body}
</body>
</html>
"""

def clean_markdown_and_protect_math(md_text):
    """
    Protects inline and block LaTeX math delimiters and converts mermaid code blocks.
    """
    math_blocks = []
    
    def save_math(match):
        idx = len(math_blocks)
        math_blocks.append(match.group(0))
        return f"@@MATHBLOCK_{idx}@@"

    # Display math $$ ... $$
    text = re.sub(r'\$\$(.*?)\$\$', save_math, md_text, flags=re.DOTALL)
    # Inline math $ ... $
    text = re.sub(r'(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)', save_math, text)

    # Convert mermaid code blocks
    text = re.sub(r'```mermaid\s*\n(.*?)\n```', r'<pre class="mermaid">\n\1\n</pre>', text, flags=re.DOTALL)

    # Convert Markdown to HTML
    html = markdown.markdown(text, extensions=['tables', 'fenced_code', 'codehilite', 'toc', 'sane_lists', 'attr_list'])

    # Restore math blocks
    for idx, mb in enumerate(math_blocks):
        html = html.replace(f"@@MATHBLOCK_{idx}@@", mb)

    return html

def build_project_report_html():
    """
    Builds the formal thesis layout for Final Year Project Report PDF.
    """
    raw_md = (DOCS_DIR / "project_report.md").read_text(encoding="utf-8")

    # Formal Title Page & University Certificates
    formal_preamble = """
<div class="title-page">
    <div>
        <div class="university-header">[UNIVERSITY_NAME]</div>
        <div class="department-header">DEPARTMENT OF COMPUTER SCIENCE AND ENGINEERING</div>
    </div>

    <div class="project-title-box">
        <h1 class="project-title">Smart Multipurpose Emergency Drone Delivery and Route Optimization System</h1>
        <div class="project-subtitle">An Integrated Multi-Objective Flight Path Optimization, Kinematic Simulation, and Autonomous Emergency Medical Supply Dispatch Engine</div>
    </div>

    <div class="report-degree-text">
        <strong>A PROJECT REPORT</strong><br>
        Submitted in partial fulfillment of the requirements for the award of the degree of<br><br>
        <span style="font-size: 13pt; font-weight: 700; color: #0f2b48;">BACHELOR OF TECHNOLOGY</span><br>
        <strong>in</strong><br>
        <span style="font-size: 12pt; font-weight: 600; color: #2563eb;">COMPUTER SCIENCE AND ENGINEERING</span>
    </div>

    <table class="meta-table">
        <tr>
            <td class="meta-left">
                <strong>Submitted By:</strong><br><br>
                <span style="font-size: 11pt; font-weight: 700; color: #0f2b48;">[STUDENT_NAME]</span><br>
                Register Number: <strong>[REGISTER_NUMBER]</strong><br>
                Department of Computer Science & Engineering<br>
                [COLLEGE_NAME]
            </td>
            <td class="meta-right">
                <strong>Under the Supervision of:</strong><br><br>
                <span style="font-size: 11pt; font-weight: 700; color: #0f2b48;">[SUPERVISOR_NAME]</span><br>
                [SUPERVISOR_DESIGNATION]<br>
                Department of Computer Science & Engineering<br>
                [COLLEGE_NAME]
            </td>
        </tr>
    </table>

    <div class="academic-year">
        ACADEMIC YEAR: [ACADEMIC_YEAR]
    </div>
</div>

<div class="certificate-box">
    <div class="university-header" style="text-align: center;">[COLLEGE_NAME]</div>
    <div class="department-header" style="text-align: center; margin-bottom: 25px;">DEPARTMENT OF COMPUTER SCIENCE AND ENGINEERING</div>
    
    <div class="cert-title">BONAFIDE CERTIFICATE</div>
    
    <p>This is to certify that this project report entitled <strong>"Smart Multipurpose Emergency Drone Delivery and Route Optimization System"</strong> is the bonafide work of <strong>[STUDENT_NAME]</strong> (Register No: <strong>[REGISTER_NUMBER]</strong>) who carried out the project under my supervision in partial fulfillment of the requirements for the award of the degree of <strong>Bachelor of Technology in Computer Science and Engineering</strong> during the academic year <strong>[ACADEMIC_YEAR]</strong>.</p>
    
    <p>The results embodied in this report have not been submitted to any other University or Institute for the award of any degree or diploma.</p>
    
    <div style="margin-top: 100px;">
        <table style="width: 100%; border: none;">
            <tr style="border: none;">
                <td style="border: none; text-align: left; width: 33%; background: transparent;">
                    ________________________<br>
                    <strong>[SUPERVISOR_NAME]</strong><br>
                    Project Supervisor<br>
                    Department of CSE
                </td>
                <td style="border: none; text-align: center; width: 33%; background: transparent;">
                    ________________________<br>
                    <strong>[HOD_NAME]</strong><br>
                    Head of the Department<br>
                    Department of CSE
                </td>
                <td style="border: none; text-align: right; width: 33%; background: transparent;">
                    ________________________<br>
                    <strong>College Seal</strong><br>
                    Place: [CITY_NAME]<br>
                    Date: [SUBMISSION_DATE]
                </td>
            </tr>
        </table>
    </div>

    <div style="margin-top: 80px;">
        <p>Submitted for the University Viva-Voce Examination held on: _____________________</p>
        <div style="display: flex; justify-content: space-between; margin-top: 40px;">
            <div style="width: 45%; text-align: left;">
                ________________________<br>
                <strong>Internal Examiner</strong>
            </div>
            <div style="width: 45%; text-align: right;">
                ________________________<br>
                <strong>External Examiner</strong>
            </div>
        </div>
    </div>
</div>

<div class="certificate-box">
    <div class="cert-title">DECLARATION OF ORIGINALITY</div>
    
    <p>I hereby declare that the project report entitled <strong>"Smart Multipurpose Emergency Drone Delivery and Route Optimization System"</strong> submitted to <strong>[COLLEGE_NAME]</strong> affiliated to <strong>[UNIVERSITY_NAME]</strong>, in partial fulfillment of the requirements for the award of the degree of <strong>Bachelor of Technology in Computer Science and Engineering</strong>, is a record of original software architecture, algorithm design, QA verification, and benchmarking work done by me under the supervision of <strong>[SUPERVISOR_NAME]</strong>, Department of Computer Science and Engineering.</p>
    
    <p>I further declare that this system operates as a software simulation engine and analytical optimization platform. The experimental flight data and machine learning benchmark evaluations presented herein are conducted using rigorous software-in-the-loop kinematics and synthetic environmental profiles as explicitly disclosed in the methodology.</p>
    
    <p>I confirm that this report has not formed the basis for the award of any degree, diploma, associateship, fellowship, or similar title in any other university or institution.</p>
    
    <div style="margin-top: 90px; text-align: right;">
        ________________________<br>
        <strong>[STUDENT_NAME]</strong><br>
        Register No: <strong>[REGISTER_NUMBER]</strong><br>
        Department of CSE, [COLLEGE_NAME]
    </div>
</div>
"""

    # Format the markdown body
    body_html = clean_markdown_and_protect_math(raw_md)

    # Append Screenshots Appendix with genuine PNGs embedded as base64
    appendix_html = """
    <div class="page-break"></div>
    <h2 id="appendix-a">Appendix A: Live Application Visualizations & Graphical User Interface Screens</h2>
    <p>This appendix presents genuine user interface screenshots captured directly from the live deployed Smart Emergency Drone Delivery System running on the local application server with active demonstration database state. All ten views correspond to authenticated user workflows across Administrator, Operator, and Requester personas.</p>
    """

    screenshots = [
        ("01_login_page.png", "Figure A.1: Multi-Role Secure Authentication Portal", "Centralized role-based access control login interface enforcing CSRF protection, password hashing (Werkzeug pbkdf2:sha256), and role assignment for Administrator, Operator, and Requester accounts."),
        ("02_admin_dashboard.png", "Figure A.2: System Administrator Control Dashboard", "Administrative oversight panel displaying overall system health, fleet utilization metrics, aggregate delivery request statuses, active simulation runs, and user access management links."),
        ("03_operator_dashboard.png", "Figure A.3: Flight Dispatcher & Drone Operator Dashboard", "Operational workstation for managing emergency requests, inspecting eligible drone availability, launching route optimization, assigning drones, and initiating flight simulations."),
        ("04_requester_dashboard.png", "Figure A.4: Emergency Medical Requester Portal", "Hospital and clinic triage view displaying submitted emergency delivery requests, real-time status tracking, estimated flight duration, and priority level feedback."),
        ("05_emergency_delivery_request_form.png", "Figure A.5: Emergency Delivery Request Intake Form", "Structured intake form enforcing geographic coordinate validation (WGS-84 bounding boxes), emergency priority classification (CRITICAL, HIGH, MEDIUM, LOW), and payload weight constraints."),
        ("06_drone_inventory.png", "Figure A.6: Fleet Inventory & Operational Status Registry", "Fleet management view displaying drone models, current operational state (AVAILABLE, IN_FLIGHT, CHARGING, MAINTENANCE), battery capacity, remaining charge percentage, and payload limits."),
        ("07_route_optimization_view.png", "Figure A.7: Multi-Objective Flight Corridor Comparison & Optimizer Interface", "Side-by-side quantitative evaluation table comparing the 4 candidate 3D flight corridors against the shortest-feasible baseline and weighted multi-objective normalized scalarization score."),
        ("08_live_drone_simulation_map.png", "Figure A.8: Real-Time Interactive Kinematic Drone Flight Tracking Map", "Interactive Leaflet.js geospatial map displaying 1-second discrete-time kinematic progress of the active drone along its chosen 3D flight corridor, accompanied by telemetry readouts."),
        ("09_dynamic_rerouting_view.png", "Figure A.9: In-Flight Dynamic Hazard Detection & Rerouting Corridor", "Visualization of in-flight dynamic rerouting triggered when environmental wind gusts exceed the safety threshold (12.0 m/s), transitioning the mission from corridor C1 to safe corridor C3."),
        ("10_analytics_and_ml_dashboard.png", "Figure A.10: Operational Telemetry & Advisory ML Prediction Analytics", "Comprehensive post-mission analytics panel presenting simulated energy consumption curves, flight duration breakdowns, CSV audit export capabilities, and Ridge Regression advisory estimates.")
    ]

    for fname, title, desc in screenshots:
        img_path = SCREENSHOTS_DIR / fname
        if img_path.exists():
            b64_data = base64.b64encode(img_path.read_bytes()).decode("utf-8")
            appendix_html += f"""
            <div class="screenshot-card">
                <img class="screenshot-img" src="data:image/png;base64,{b64_data}" alt="{title}">
                <div class="screenshot-caption">{title}</div>
                <div class="screenshot-desc">{desc}</div>
            </div>
            """

    full_html = HTML_TEMPLATE.format(
        title="Final Year Project Report - Smart Multipurpose Emergency Drone Delivery System",
        body=formal_preamble + body_html + appendix_html
    )
    return full_html

def build_algorithm_explanations_html():
    raw_md = (DOCS_DIR / "algorithm_explanations.md").read_text(encoding="utf-8")
    body_html = clean_markdown_and_protect_math(raw_md)
    return HTML_TEMPLATE.format(
        title="Algorithm Explanations & Pseudocode Reference - Smart Emergency Drone Delivery System",
        body=body_html
    )

def build_testing_documentation_html():
    raw_md = (DOCS_DIR / "testing_documentation.md").read_text(encoding="utf-8")
    # Replace PASS with styled badge
    raw_md = raw_md.replace("`PASS`", '<span class="badge badge-pass">PASS</span>')
    raw_md = raw_md.replace("`PASSED`", '<span class="badge badge-pass">PASSED</span>')
    body_html = clean_markdown_and_protect_math(raw_md)
    return HTML_TEMPLATE.format(
        title="Testing Documentation & QA Verification Report - Smart Emergency Drone Delivery System",
        body=body_html
    )

def build_viva_preparation_html():
    raw_md = (DOCS_DIR / "viva_preparation.md").read_text(encoding="utf-8")

    # Format Questions and Answers into structured viva cards
    # Pattern: ### Q(\d+): (.*?)\n(.*?)(?=(?:### Q|\n## |\Z))
    def format_viva_cards(text):
        pattern = r'### Q(\d+):\s*(.*?)\n(.*?)(?=(?:### Q\d+|\n## |\Z))'
        
        def card_replacer(match):
            q_num = match.group(1)
            q_title = match.group(2).strip()
            ans_body = match.group(3).strip()
            ans_html = clean_markdown_and_protect_math(ans_body)
            return f"""
<div class="viva-card">
    <div class="viva-question">
        <span class="viva-question-num">Q{q_num}</span>
        <span>{q_title}</span>
    </div>
    <div class="viva-answer">
        {ans_html}
    </div>
</div>
"""
        return re.sub(pattern, card_replacer, text, flags=re.DOTALL)

    processed_md = format_viva_cards(raw_md)
    body_html = clean_markdown_and_protect_math(processed_md)
    return HTML_TEMPLATE.format(
        title="Viva Voce Defense Guide (55 Questions & Answers) - Smart Emergency Drone Delivery System",
        body=body_html
    )

def generate_all_pdfs():
    print("[*] Preparing HTML files...")

    targets = [
        ("Final_Year_Project_Report.pdf", build_project_report_html(), "Final Year Project Report (Thesis Layout)"),
        ("Algorithm_Explanations.pdf", build_algorithm_explanations_html(), "Algorithm Explanations & Pseudocode Reference"),
        ("Testing_Documentation.pdf", build_testing_documentation_html(), "Testing Documentation & QA Verification Report"),
        ("Viva_Preparation_Guide.pdf", build_viva_preparation_html(), "Viva Voce Defense Guide (55 Questions)")
    ]

    with sync_playwright() as p:
        print("[*] Launching browser (Microsoft Edge)...")
        browser = p.chromium.launch(channel="msedge", headless=True)

        for filename, html_content, description in targets:
            temp_html_path = PDF_DIR / f"{filename}.temp.html"
            temp_html_path.write_text(html_content, encoding="utf-8")
            
            output_pdf_path = PDF_DIR / filename
            print(f"[*] Generating {filename} ({description})...")
            
            page = browser.new_page()
            page.goto(temp_html_path.resolve().as_uri(), wait_until="networkidle")
            # Wait for KaTeX and Mermaid to render completely
            page.wait_for_timeout(3000)

            page.pdf(
                path=str(output_pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "22mm", "bottom": "22mm", "left": "18mm", "right": "18mm"},
                display_header_footer=True,
                header_template='<div style="font-size: 8pt; font-family: Segoe UI, sans-serif; color: #94a3b8; width: 100%; text-align: left; padding-left: 18mm; text-transform: uppercase; letter-spacing: 0.5px;">B.Tech CSE Academic Submission &nbsp;|&nbsp; Smart Emergency Drone Delivery</div>',
                footer_template='<div style="font-size: 8.5pt; font-family: Segoe UI, sans-serif; color: #64748b; width: 100%; text-align: right; padding-right: 18mm;">Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>'
            )
            page.close()
            
            # Clean up temp html
            temp_html_path.unlink(missing_ok=True)
            print(f"[+] Successfully generated: {output_pdf_path} (Size: {output_pdf_path.stat().st_size:,} bytes)")

        browser.close()
    
    print("\n[+] All 4 Academic Submission PDFs generated successfully!")

if __name__ == "__main__":
    generate_all_pdfs()
