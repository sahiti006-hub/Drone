"""Generate a professional 15-slide PowerPoint presentation (.pptx).

Uses python-pptx to generate docs/final_submission/pptx/Final_Year_Project_Presentation.pptx
Adheres to strict university engineering defense guidelines:
- 16:9 widescreen layout
- Navy blue, white, and accent blue color palette
- Formatted tables, architectural cards, mathematical callouts, and speaker notes on every slide
"""

import sys
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "docs" / "final_submission" / "pptx" / "Final_Year_Project_Presentation.pptx"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

# Color Palette
DARK_NAVY = RGBColor(15, 23, 42)      # #0f172a
PRIMARY_BLUE = RGBColor(30, 64, 175)  # #1e40af
ACCENT_BLUE = RGBColor(2, 132, 199)   # #0284c7
LIGHT_BG = RGBColor(248, 250, 252)    # #f8fafc
CARD_BG = RGBColor(239, 246, 255)     # #eff6ff
CARD_BORDER = RGBColor(191, 219, 254) # #bfdbfe
TEXT_DARK = RGBColor(30, 41, 59)      # #1e293b
TEXT_MUTED = RGBColor(100, 116, 139)  # #64748b
TEXT_WHITE = RGBColor(255, 255, 255)
GREEN = RGBColor(22, 163, 74)         # #16a34a
GOLD = RGBColor(217, 119, 6)          # #d97706
RED = RGBColor(220, 38, 38)           # #dc2626


def create_base_slide(prs, title, category="FINAL-YEAR B.TECH CSE CAPSTONE DEFENSE", dark_mode=False):
    """Create a standardized slide with header banner, category kicker, and background."""
    blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)

    # Background fill
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.line.fill.background()
    bg.fill.solid()
    bg.fill.fore_color.rgb = DARK_NAVY if dark_mode else LIGHT_BG

    if not dark_mode:
        # Header banner card
        header_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.733), Inches(0.9))
        tf = header_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

        p_kicker = tf.paragraphs[0]
        p_kicker.text = category.upper()
        p_kicker.font.size = Pt(10)
        p_kicker.font.bold = True
        p_kicker.font.color.rgb = ACCENT_BLUE

        p_title = tf.add_paragraph()
        p_title.text = title
        p_title.font.size = Pt(22)
        p_title.font.bold = True
        p_title.font.color.rgb = DARK_NAVY
        p_title.space_before = Pt(4)

        # Header underline rule
        rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.35), Inches(11.733), Inches(0.02))
        rule.line.fill.background()
        rule.fill.solid()
        rule.fill.fore_color.rgb = CARD_BORDER

    return slide


def add_card(slide, left, top, width, height, title="", bg_color=CARD_BG, border_color=CARD_BORDER):
    """Add a structured container card."""
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    card.line.color.rgb = border_color
    card.line.width = Pt(1.2)
    card.fill.solid()
    card.fill.fore_color.rgb = bg_color

    if title:
        tb = slide.shapes.add_textbox(Inches(left + 0.2), Inches(top + 0.15), Inches(width - 0.4), Inches(0.4))
        tf = tb.text_frame
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = PRIMARY_BLUE

    return card


def set_speaker_notes(slide, notes_text):
    """Attach speaker notes to slide."""
    notes_slide = slide.notes_slide
    text_frame = notes_slide.notes_text_frame
    text_frame.text = notes_text


def build_presentation():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # ==========================================================================
    # SLIDE 1: Title Slide (Dark Navy)
    # ==========================================================================
    s1 = create_base_slide(prs, "", dark_mode=True)
    tb = s1.shapes.add_textbox(Inches(1.2), Inches(1.2), Inches(10.9), Inches(5.0))
    tf = tb.text_frame
    tf.word_wrap = True

    p0 = tf.paragraphs[0]
    p0.text = "DEPARTMENT OF COMPUTER SCIENCE & ENGINEERING • B.TECH DEFENSE"
    p0.font.size = Pt(12)
    p0.font.bold = True
    p0.font.color.rgb = ACCENT_BLUE

    p1 = tf.add_paragraph()
    p1.text = "Smart Multipurpose Emergency Drone Delivery\n& Route Optimization System"
    p1.font.size = Pt(32)
    p1.font.bold = True
    p1.font.color.rgb = TEXT_WHITE
    p1.space_before = Pt(14)

    p2 = tf.add_paragraph()
    p2.text = "Autonomous Medical Logistics, 3D Airspace Corridor Optimization, and Discrete-Time Flight Simulation"
    p2.font.size = Pt(15)
    p2.font.color.rgb = CARD_BORDER
    p2.space_before = Pt(12)

    p3 = tf.add_paragraph()
    p3.text = "Candidate Name(s): [Student Name 1, Roll No. 1] • [Student Name 2, Roll No. 2] • [Student Name 3, Roll No. 3]\nSupervisor / Guide: [Prof. Name, Designation] | Academic Year: 2025–2026"
    p3.font.size = Pt(12)
    p3.font.color.rgb = RGBColor(148, 163, 184)
    p3.space_before = Pt(28)

    set_speaker_notes(s1, "Good morning, respected external examiners and faculty members. Today our team presents our final-year B.Tech capstone project: the Smart Multipurpose Emergency Drone Delivery and Route Optimization System. In this presentation, we will walk you through our system architecture, 3D route optimization models, multi-drone allocation, dynamic in-flight rerouting, advisory ML validation, and 125 automated verification tests.")

    # ==========================================================================
    # SLIDE 2: Introduction & Clinical Motivation
    # ==========================================================================
    s2 = create_base_slide(prs, "Introduction & Clinical Emergency Motivation")
    
    # 3 Cards: Golden Hour, Target Payloads, Technical Challenge
    add_card(s2, 0.8, 1.6, 3.7, 5.2, "Clinical Golden Hour")
    tb = s2.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(3.3), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "• Clinical Threshold:\nHemorrhagic shock, acute neurotoxic envenomation, and cardiac arrest require intervention in <60 minutes.\n\n• Ground Transit Latency:\nSurface ambulances in congested urban cores or rugged rural areas experience high travel-time variance.\n\n• Life-Saving Advantage:\nLow-altitude aerial multi-rotors bypass road traffic completely."

    add_card(s2, 4.8, 1.6, 3.7, 5.2, "Target Medical Payloads")
    tb = s2.shapes.add_textbox(Inches(5.0), Inches(2.2), Inches(3.3), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "• Whole Blood Units:\n2.20 kg cold-chain payload for emergency trauma transfusions.\n\n• Antivenom Vials:\n1.20 kg snakebite serum for rural primary health centers.\n\n• Portable AED Defibrillators:\n3.00 kg automated external defibrillators for out-of-hospital cardiac arrest.\n\n• Surgical Emergency Kits:\n4.50 kg sterile instruments."

    add_card(s2, 8.8, 1.6, 3.7, 5.2, "Core Engineering Challenge")
    tb = s2.shapes.add_textbox(Inches(9.0), Inches(2.2), Inches(3.3), Inches(4.3))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "• Constrained Energy Density:\nMulti-rotors have limited battery storage and cannot afford inefficient routes.\n\n• Safety-Critical Margins:\nMandatory 15% non-depletable reserve to prevent mid-air battery exhaustion.\n\n• Atmospheric Sensitivity:\nHeadwinds and localized convective squalls require dynamic re-evaluation."

    set_speaker_notes(s2, "In acute medical emergencies, the Golden Hour is decisive. Transporting whole blood or antivenom via surface ambulance often encounters severe road gridlock. Drones decouple emergency transit from ground congestion; however, multi-rotors operate under tight battery capacities and payload limits. Our project automates this logistics pipeline safely.")

    # ==========================================================================
    # SLIDE 3: Problem Statement
    # ==========================================================================
    s3 = create_base_slide(prs, "Problem Statement: Logistical & Algorithmic Deficiencies")
    
    add_card(s3, 0.8, 1.6, 5.7, 2.4, "1. Surface Transport Vulnerability")
    tb = s3.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(5.3), Inches(1.8))
    tb.text_frame.word_wrap = True
    tb.text_frame.text = "• Road gridlock, construction, and disaster damage create unpredictable transit delays.\n• Isolated rural clinics and flood-isolated perimeters lack passable physical roadways."

    add_card(s3, 6.8, 1.6, 5.7, 2.4, "2. Naive Aerial Point-to-Point Routing")
    tb = s3.shapes.add_textbox(Inches(7.0), Inches(2.1), Inches(5.3), Inches(1.8))
    tb.text_frame.word_wrap = True
    tb.text_frame.text = "• Blind Euclidean straight-line dispatching ignores urban obstacle towers, crosswind turbulence, and climb energy.\n• Shortest 2D paths often choose high altitudes that burn excessive climb power."

    add_card(s3, 0.8, 4.3, 5.7, 2.5, "3. Lack of Governance & Atomic Dispatch")
    tb = s3.shapes.add_textbox(Inches(1.0), Inches(4.8), Inches(5.3), Inches(1.8))
    tb.text_frame.word_wrap = True
    tb.text_frame.text = "• Dispatching platforms frequently lack concurrency locks, risking double-allocation of available drones.\n• Absence of auditable historical records for regulatory incident reviews."

    add_card(s3, 6.8, 4.3, 5.7, 2.5, "4. Suboptimal Fleet Allocation Under Scarcity")
    tb = s3.shapes.add_textbox(Inches(7.0), Inches(4.8), Inches(5.3), Inches(1.8))
    tb.text_frame.word_wrap = True
    tb.text_frame.text = "• Standard First-Come-First-Served (FCFS) matching allows routine cargo to claim airframes, stranding critical blood requests.\n• Requires clinical triage ranking with capacity waste minimization."

    set_speaker_notes(s3, "Our problem statement isolates four major challenges: surface transport failure, naive point-to-point routing flaws, concurrency race conditions, and sub-optimal FIFO allocation under fleet scarcity.")

    # ==========================================================================
    # SLIDE 4: Existing System vs. Proposed System
    # ==========================================================================
    s4 = create_base_slide(prs, "System Comparison: Existing Ground/Naive vs. Proposed System")

    # Table on slide
    rows, cols = 6, 3
    table_shape = s4.shapes.add_table(rows, cols, Inches(0.8), Inches(1.7), Inches(11.733), Inches(4.8))
    table = table_shape.table
    table.columns[0].width = Inches(2.8)
    table.columns[1].width = Inches(4.4)
    table.columns[2].width = Inches(4.533)

    headers = ["Evaluation Dimension", "Existing Ground / Naive Systems", "Proposed Smart Drone System"]
    for i, h in enumerate(headers):
        cell = table.cell(0, i)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK_NAVY
        for p in cell.text_frame.paragraphs:
            p.font.bold = True
            p.font.color.rgb = TEXT_WHITE
            p.font.size = Pt(13)

    data = [
        ("Transit Medium", "2D Surface road networks (Google Maps, OSRM)", "3D Low-altitude Very Low Level (VLL) Airspace"),
        ("Optimization Metric", "Single-objective shortest distance", "Multi-objective (distance, duration, energy, climb penalty)"),
        ("Safety Constraints", "Assumes infinite range; no battery model", "Strict 15% battery reserve, payload rating, weather cutoffs"),
        ("Meteorological Response", "Static pre-departure routing", "Dynamic in-flight rerouting with original route DB preservation"),
        ("Fleet Dispatching", "Manual / First-Come-First-Served (FCFS)", "Bipartite Priority Best-Fit matching based on clinical triage"),
    ]

    for row_idx, row_data in enumerate(data, start=1):
        for col_idx, text in enumerate(row_data):
            cell = table.cell(row_idx, col_idx)
            cell.text = text
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(255, 255, 255) if row_idx % 2 == 1 else CARD_BG
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(11)
                p.font.color.rgb = TEXT_DARK
                if col_idx == 0:
                    p.font.bold = True

    set_speaker_notes(s4, "This comparison matrix highlights our engineering contributions. Unlike traditional single-objective tools, our system couples 3D airspace corridors with multi-objective scalarization, enforced battery reserves, dynamic in-flight rerouting, and priority-aware batch allocation.")

    # ==========================================================================
    # SLIDE 5: Proposed System Overview & Key Capabilities
    # ==========================================================================
    s5 = create_base_slide(prs, "Proposed System Architecture & Core Modules")

    modules = [
        ("1. Role-Based Portals", "Tailored dashboards for Requesters, Fleet Operators, and Administrators with strict RBAC."),
        ("2. 3D Corridor Generator", "Synthesizes Direct, Detour, and High-Altitude corridors without relying on road networks."),
        ("3. Feasibility Checker", "Validates payload ratings, 15% non-depletable battery reserve, wind (<=12 m/s), and rain (<=8 mm/h)."),
        ("4. Multi-Objective Optimizer", "Min-max normalized scalarization balancing time, energy, distance, and maneuver penalties."),
        ("5. Priority Batch Allocator", "Triage-driven matching pairing high-urgency requests while minimizing capacity headroom waste."),
        ("6. Kinematic Simulation Cockpit", "Discrete-time waypoint propagation on interactive Leaflet maps with pause/resume controls."),
        ("7. Dynamic Rerouting Engine", "Safety-mandated mid-flight re-evaluation with immutable audit trails and route preservation."),
        ("8. Advisory ML Predictor", "L2-regularized Ridge regression providing instant duration and energy estimations."),
    ]

    for i, (mod_title, mod_desc) in enumerate(modules):
        col = i % 4
        row = i // 4
        x = 0.8 + col * 2.95
        y = 1.6 + row * 2.6
        add_card(s5, x, y, 2.85, 2.4, mod_title)
        tb = s5.shapes.add_textbox(Inches(x + 0.15), Inches(y + 0.65), Inches(2.55), Inches(1.6))
        tb.text_frame.word_wrap = True
        tb.text_frame.text = mod_desc
        for p in tb.text_frame.paragraphs:
            p.font.size = Pt(10)
            p.font.color.rgb = TEXT_DARK

    set_speaker_notes(s5, "The proposed system comprises eight tightly integrated core modules, spanning role-based access control, 3D geometric corridor synthesis, multi-objective optimization, kinematic simulation, and advisory machine learning flight estimation.")

    # ==========================================================================
    # SLIDE 6: Objectives & Scope of Work
    # ==========================================================================
    s6 = create_base_slide(prs, "Objectives & Academic Scope Disclosures")

    add_card(s6, 0.8, 1.6, 5.7, 5.2, "Core Project Objectives")
    tb = s6.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(5.3), Inches(4.4))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "1. Clean Layered Architecture:\nDecouple HTTP presentation, business logic services, and relational persistence.\n\n2. Deterministic Corridor Optimization:\nFormulate min-max normalized scalarized cost model benchmarking against shortest-feasible baselines.\n\n3. Priority Fleet Dominance:\nDemonstrate that Priority Best-Fit outperforms greedy FCFS in clinical triage fulfillment.\n\n4. Dynamic Reroute Auditability:\nPreserve original routes in the database during in-flight weather switches.\n\n5. Quality Assurance:\nAchieve >80% statement test coverage with zero regressions."

    add_card(s6, 6.8, 1.6, 5.7, 5.2, "Academic Scope & Disclosures", bg_color=RGBColor(255, 251, 235), border_color=RGBColor(253, 230, 138))
    tb = s6.shapes.add_textbox(Inches(7.0), Inches(2.2), Inches(5.3), Inches(4.4))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "⚠️ MANDATORY SIMULATION RESEARCH DISCLOSURES:\n\n1. Pure Software Simulation:\nThe system operates strictly in software simulation mode. It does NOT command physical drone avionics (e.g. PX4/MAVLink) or civil air-traffic transponders.\n\n2. Aerodynamic Energy Modeling:\nPower calculations derive from analytical multi-rotor equations rather than physical chemical battery discharge curves.\n\n3. Synthetic ML Training Data:\nThe advisory ML flight prediction module was trained and evaluated exclusively on synthetic simulator data with Gaussian noise (sigma=0.05). No real-world UAV flight sensor telemetry is used."
    for p in tf.paragraphs:
        p.font.size = Pt(11)
        p.font.color.rgb = RGBColor(146, 64, 14)

    set_speaker_notes(s6, "For complete academic integrity, we emphasize our project scope: this is a software simulation and optimization platform. We model aerodynamics, kinematics, and weather mathematically, and our ML module is trained on synthetic physical equations.")

    # ==========================================================================
    # SLIDE 7: System Architecture & Layered Design
    # ==========================================================================
    s7 = create_base_slide(prs, "System Architecture: Layered Clean Architecture")

    layers = [
        ("Presentation Layer", "HTML5, CSS3, Vanilla ES6 JavaScript, Responsive Bootstrap Grid, Leaflet.js Interactive Cockpit", PRIMARY_BLUE),
        ("Controller Layer", "Flask Blueprints: /auth, /requests, /drones, /simulation, /analytics, /dashboard (REST APIs & Views)", DARK_NAVY),
        ("Business Services", "RouteOptimizer, AssignmentService, DroneAllocationService, SimulationService, PredictionService", PRIMARY_BLUE),
        ("Persistence Layer", "SQLAlchemy 2.0 ORM Models: User, Drone, DeliveryRequest, Route, RouteWaypoint, DroneAssignment, SimulationRun", DARK_NAVY),
        ("Database Storage", "Relational 3NF Database: MySQL 8.0 Server (Production) / SQLite 3 (Testing & Local Development)", PRIMARY_BLUE),
    ]

    for idx, (l_title, l_desc, color) in enumerate(layers):
        y = 1.6 + idx * 1.05
        card = slide_shape = s7.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1.2), Inches(y), Inches(10.933), Inches(0.85))
        card.line.color.rgb = color
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG

        tb = s7.shapes.add_textbox(Inches(1.4), Inches(y + 0.08), Inches(10.5), Inches(0.7))
        tf = tb.text_frame
        tf.word_wrap = True
        p1 = tf.paragraphs[0]
        p1.text = l_title.upper()
        p1.font.bold = True
        p1.font.size = Pt(12)
        p1.font.color.rgb = color

        p2 = tf.add_paragraph()
        p2.text = l_desc
        p2.font.size = Pt(10)
        p2.font.color.rgb = TEXT_DARK

    set_speaker_notes(s7, "Our architecture strictly adheres to Layered Clean Architecture. This separation decouples HTTP routing from core domain logic, ensuring our route optimizer and allocation algorithms can be thoroughly tested without running a live HTTP server.")

    # ==========================================================================
    # SLIDE 8: Technology Stack & Implementation Frameworks
    # ==========================================================================
    s8 = create_base_slide(prs, "Technology Stack & Engineering Tools")

    tech_cards = [
        ("Backend Framework", "• Python 3.14 Runtime\n• Flask 3.1 Application Framework\n• Application Factory Pattern\n• Modular Blueprints\n• WSGI Entry Point (Waitress/Gunicorn)"),
        ("Database & ORM", "• SQLAlchemy 2.0 (Modern 2.0 Syntax)\n• 3NF Relational Schema Design\n• Flask-Migrate & Alembic Migrations\n• MySQL 8.0 / SQLite 3 Database\n• Row-Level Locking (`with_for_update`)"),
        ("Frontend & Cockpit", "• Leaflet.js Mapping Library\n• OpenStreetMap Geodesic Tiles\n• Vanilla JavaScript Telemetry HUD\n• Responsive Bootstrap Grid\n• Pure CSS Design System"),
        ("Quality & Security", "• Pytest 9.2 Testing Framework\n• Pytest-Cov (83% statement coverage)\n• Flask-WTF CSRF Protection\n• PBKDF2-HMAC-SHA256 Password Hashing\n• CSV Formula Injection Sanitization"),
    ]

    for i, (title, content) in enumerate(tech_cards):
        x = 0.8 + i * 2.95
        add_card(s8, x, 1.6, 2.85, 5.2, title)
        tb = s8.shapes.add_textbox(Inches(x + 0.15), Inches(2.2), Inches(2.55), Inches(4.3))
        tb.text_frame.word_wrap = True
        tb.text_frame.text = content
        for p in tb.text_frame.paragraphs:
            p.font.size = Pt(11)
            p.font.color.rgb = TEXT_DARK

    set_speaker_notes(s8, "Our technology stack combines Python 3.14, Flask 3.1, SQLAlchemy 2.0, MySQL, Leaflet.js, and Pytest. We chose tools that provide complete determinism, robust security, and cross-platform portability across Windows and Linux.")

    # ==========================================================================
    # SLIDE 9: Route Optimization Methodology & Multi-Objective Model
    # ==========================================================================
    s9 = create_base_slide(prs, "Route Optimization: 3D Corridors & Scalarized Cost Model")

    add_card(s9, 0.8, 1.6, 5.7, 5.2, "Geometric Corridor Generation")
    tb = s9.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(5.3), Inches(4.4))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "• Corridor 1: Direct Air Corridor\nDirect great-circle geodesic track at 60m AGL cruise altitude.\n\n• Corridor 2: Northern Detour\nMidpoint deflected northward by +1.2 km (+0.0108 deg) to circumvent high-risk central urban corridors.\n\n• Corridor 3: Southern Detour\nMidpoint deflected southward by -1.2 km (-0.0108 deg) providing alternative wind-vector alignment.\n\n• Corridor 4: High Altitude Corridor\nMaintains direct 2D track elevated to 120m AGL to clear urban high-rises at the cost of vertical climb power."

    add_card(s9, 6.8, 1.6, 5.7, 5.2, "Mathematical Scalarization Model")
    tb = s9.shapes.add_textbox(Inches(7.0), Inches(2.2), Inches(5.3), Inches(4.4))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "• Min-Max Feature Normalization:\nMetrics are normalized to eliminate unit disparity:\nx* = (x - min(x)) / (max(x) - min(x) + eps)\n\n• Composite Objective Cost Function:\nJ(c) = 0.25 * d* + 0.35 * t* + 0.30 * e* + 0.10 * p*\n\n• Calibrated Objective Weights:\n- Duration (wt = 0.35): Clinical emergency urgency\n- Energy (we = 0.30): Battery reserve preservation\n- Distance (wd = 0.25): Lateral path efficiency\n- Penalty (wp = 0.10): Vertical climb & banking turns\n\n• Optimization Selection:\nOptimal Corridor c* = argmin J(c) among feasible paths."

    set_speaker_notes(s9, "Slide 9 presents our multi-objective route optimizer. Rather than relying on single-objective distance, we generate 4 distinct 3D flight corridors and evaluate them using Min-Max Normalized Scalarization across distance, duration, aerodynamic energy, and climb penalties.")

    # ==========================================================================
    # SLIDE 10: Multi-Drone Batch Allocation: Priority Best-Fit vs. FCFS
    # ==========================================================================
    s10 = create_base_slide(prs, "Multi-Drone Allocation: Priority Best-Fit vs. FCFS Baseline")

    # Table on slide
    rows, cols = 5, 5
    table_shape = s10.shapes.add_table(rows, cols, Inches(0.8), Inches(1.6), Inches(11.733), Inches(3.2))
    table = table_shape.table
    table.columns[0].width = Inches(1.5)
    table.columns[1].width = Inches(2.3)
    table.columns[2].width = Inches(2.3)
    table.columns[3].width = Inches(2.8)
    table.columns[4].width = Inches(2.833)

    h_data = ["Strategy", "Matched Requests", "Unmatched Requests", "High-Priority Fulfillment", "Total Priority Score"]
    for i, h in enumerate(h_data):
        cell = table.cell(0, i)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK_NAVY
        for p in cell.text_frame.paragraphs:
            p.font.bold = True
            p.font.color.rgb = TEXT_WHITE
            p.font.size = Pt(11)

    r_data = [
        ("FCFS Greedy Baseline", "Req #1 (LOW: 1.5kg)\nReq #2 (MED: 4.2kg)", "Req #3 (HIGH: 2.0kg)\nReq #4 (CRIT: 2.2kg)", "0.0% (0 / 2 high-priority)", "3 (1 + 2)"),
        ("Priority Best-Fit", "Req #4 (CRIT: 2.2kg)\nReq #3 (HIGH: 2.0kg)", "Req #2 (MED: 4.2kg)\nReq #1 (LOW: 1.5kg)", "100.0% (2 / 2 high-priority)", "7 (4 + 3)"),
        ("Empirical Delta", "Replaced routine cargo with life-saving blood", "Routine supplies safely held in queue", "+100.0% improvement in critical fulfillment", "+133% increase in clinical triage utility"),
        ("Headroom Efficiency", "Avg Headroom Waste: 3.9 kg", "Avg Headroom Waste: 2.1 kg", "46.1% reduction in wasted payload capacity", "Heavy-lifters reserved for heavy cargo"),
    ]

    for row_idx, r in enumerate(r_data, start=1):
        for col_idx, text in enumerate(r):
            cell = table.cell(row_idx, col_idx)
            cell.text = text
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(255, 255, 255) if row_idx % 2 == 1 else CARD_BG
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(10)
                p.font.color.rgb = TEXT_DARK
                if col_idx == 0:
                    p.font.bold = True

    add_card(s10, 0.8, 5.1, 11.733, 1.8, "Key Algorithmic Takeaway for Panel Evaluators")
    tb = s10.shapes.add_textbox(Inches(1.0), Inches(5.6), Inches(11.3), Inches(1.2))
    tb.text_frame.word_wrap = True
    tb.text_frame.text = "Under fleet scarcity (2 drones vs. 4 requests), the First-Come-First-Served baseline allocates airframes to routine non-urgent cargo simply because it arrived first, leaving life-threatening CRITICAL blood requests grounded. Priority Best-Fit ensures critical medical needs take absolute precedence while simultaneously minimizing wasted payload headroom."

    set_speaker_notes(s10, "Slide 10 details our multi-drone allocation benchmark. Under FCFS, routine packages grounded critical emergency requests. Priority Best-Fit achieved 100% high-priority fulfillment, increased clinical triage score by 133%, and cut capacity headroom waste in half.")

    # ==========================================================================
    # SLIDE 11: Dynamic Weather-Based In-Flight Rerouting
    # ==========================================================================
    s11 = create_base_slide(prs, "Dynamic Simulation & In-Flight Environmental Rerouting")

    steps = [
        ("1. Pre-Flight Dispatch", "Mission initialized on Direct Corridor (#1). Drone steps to 17.7% progress under clear weather."),
        ("2. Hazard Detection", "In-flight sensor update reports severe crosswind shear (7.8 m/s) and localized precipitation (4.0 mm/h)."),
        ("3. Mid-Air Re-Planning", "Engine recalculates remaining flight from drone's current coordinate (lat, lon) to destination."),
        ("4. Policy Switch", "Under SAFETY_MANDATED policy, engine adopts safer replacement corridor (#2) to navigate around hazard."),
        ("5. DB Preservation", "Original Route #1 is preserved intact in the database for post-mission incident audit compliance."),
        ("6. Touchdown", "Simulation completes flight on replacement corridor, reaching DELIVERED status safely."),
    ]

    for i, (s_title, s_desc) in enumerate(steps):
        col = i % 3
        row = i // 3
        x = 0.8 + col * 3.95
        y = 1.6 + row * 2.6
        add_card(s11, x, y, 3.85, 2.4, s_title)
        tb = s11.shapes.add_textbox(Inches(x + 0.15), Inches(y + 0.65), Inches(3.55), Inches(1.6))
        tb.text_frame.word_wrap = True
        tb.text_frame.text = s_desc
        for p in tb.text_frame.paragraphs:
            p.font.size = Pt(11)
            p.font.color.rgb = TEXT_DARK

    set_speaker_notes(s11, "Dynamic rerouting protects the drone from mid-flight weather incidents. The simulation recalculates alternative corridors from the drone's instantaneous coordinate, switches under the SAFETY_MANDATED policy, and permanently preserves the original route in the database for audit compliance.")

    # ==========================================================================
    # SLIDE 12: Advisory Machine Learning Flight Prediction Module
    # ==========================================================================
    s12 = create_base_slide(prs, "Advisory Machine Learning Flight Prediction Module")

    rows, cols = 4, 5
    table_shape = s12.shapes.add_table(rows, cols, Inches(0.8), Inches(1.6), Inches(11.733), Inches(2.6))
    table = table_shape.table
    table.columns[0].width = Inches(2.5)
    table.columns[1].width = Inches(2.3)
    table.columns[2].width = Inches(2.3)
    table.columns[3].width = Inches(2.3)
    table.columns[4].width = Inches(2.333)

    ml_headers = ["Prediction Target", "Evaluated Metric", "Physics Baseline Formula", "Proposed Ridge ML Model", "Improvement / Delta"]
    for i, h in enumerate(ml_headers):
        cell = table.cell(0, i)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK_NAVY
        for p in cell.text_frame.paragraphs:
            p.font.bold = True
            p.font.color.rgb = TEXT_WHITE
            p.font.size = Pt(11)

    ml_rows = [
        ("Flight Duration (min)", "Mean Absolute Error (MAE)", "2.5495 min", "1.0397 min", "+59.2% error reduction"),
        ("Flight Duration (min)", "R² Coefficient", "0.8930", "0.9754", "Fits synthetic kinematics"),
        ("Energy Drain (Wh)", "Mean Absolute Error (MAE)", "21.2845 Wh", "7.8514 Wh", "+63.1% error reduction"),
    ]

    for row_idx, r in enumerate(ml_rows, start=1):
        for col_idx, text in enumerate(r):
            cell = table.cell(row_idx, col_idx)
            cell.text = text
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(255, 255, 255) if row_idx % 2 == 1 else CARD_BG
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(10)
                p.font.color.rgb = TEXT_DARK
                if col_idx in (0, 3):
                    p.font.bold = True

    add_card(s12, 0.8, 4.4, 11.733, 2.4, "Model Architecture & Academic Methodology Disclaimer", bg_color=RGBColor(255, 251, 235), border_color=RGBColor(253, 230, 138))
    tb = s12.shapes.add_textbox(Inches(1.0), Inches(5.0), Inches(11.3), Inches(1.7))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "• Model Architecture: L2-Regularized Ridge Regression (Ridge-OLS-Poly-v1.0, alpha=1.0) with closed-form solution: w = (X^T X + alpha I)^-1 X^T y.\n• Features (D=6): Distance, Payload, Wind Speed, Cruise Speed, Payload*Distance Interaction, and Wind^2 Quadratic Drag.\n• Methodology Disclaimer: Evaluated on N=80 held-out synthetic test samples (seed=42). The high R² reflects successful function approximation of the underlying physics equations rather than real-world UAV flight. Predictions are strictly advisory."
    for p in tf.paragraphs:
        p.font.size = Pt(10)
        p.font.color.rgb = RGBColor(146, 64, 14)

    set_speaker_notes(s12, "Our advisory ML module uses Ridge Regression with polynomial interaction terms. On held-out test data, it reduced duration MAE by 59.2% and energy MAE by 63.1% compared to physics baselines. We explicitly disclose that the model approximates synthetic simulation kinematics and functions strictly as an advisory tool.")

    # ==========================================================================
    # SLIDE 13: Testing, Quality Assurance & Verification
    # ==========================================================================
    s13 = create_base_slide(prs, "Testing, Quality Assurance & Verification Results")

    stats_cards = [
        ("Total Automated Tests", "125 Passed", "100% Pass Rate across 16 test modules", GREEN),
        ("Statement Coverage", "83% Coverage", "Across 2,851 lines of application code", PRIMARY_BLUE),
        ("Execution Speed", "20.71 Seconds", "Fast, deterministic regression test cycle", ACCENT_BLUE),
        ("Safety Assertions", "100% Verified", "Battery, payload, and storm gating confirmed", GREEN),
    ]

    for i, (title, stat, desc, color) in enumerate(stats_cards):
        x = 0.8 + i * 2.95
        add_card(s13, x, 1.6, 2.85, 1.8, "")
        tb = s13.shapes.add_textbox(Inches(x + 0.1), Inches(1.75), Inches(2.65), Inches(1.5))
        tf = tb.text_frame
        tf.word_wrap = True
        p1 = tf.paragraphs[0]
        p1.text = stat
        p1.font.size = Pt(22)
        p1.font.bold = True
        p1.font.color.rgb = color

        p2 = tf.add_paragraph()
        p2.text = title
        p2.font.bold = True
        p2.font.size = Pt(11)
        p2.font.color.rgb = DARK_NAVY
        p2.space_before = Pt(4)

        p3 = tf.add_paragraph()
        p3.text = desc
        p3.font.size = Pt(9)
        p3.font.color.rgb = TEXT_MUTED

    add_card(s13, 0.8, 3.6, 11.733, 3.2, "Coverage Breakdown Across Critical Application Services")
    tb = s13.shapes.add_textbox(Inches(1.0), Inches(4.2), Inches(11.3), Inches(2.4))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "• app/services/route_optimizer.py      : 94% Coverage (Candidate generation, feasibility validation, scalarization)\n• app/services/prediction_service.py   : 98% Coverage (Ridge regressor fit/predict, polynomial features, metrics)\n• app/services/analytics_service.py    : 92% Coverage (Dashboard metrics, discrepancy audit, formula-safe CSV)\n• app/services/simulation_service.py   : 90% Coverage (Kinematic stepping, pause/resume, in-flight rerouting)\n• app/services/drone_allocation_service: 89% Coverage (Priority Best-Fit matching, FCFS baseline, batch dispatch)\n• app/models/delivery_request.py       : 97% Coverage (Lifecycle state transitions, priority enums)\n• Security & Concurrency Verification  : Zero SQL injection, CSRF enforcement, IDOR horizontal privilege defense."
    for p in tf.paragraphs:
        p.font.size = Pt(10)
        p.font.color.rgb = TEXT_DARK

    set_speaker_notes(s13, "Software reliability is substantiated by empirical test execution: 125 automated tests pass with 83% statement coverage across 2,851 lines of code in under 21 seconds. Critical services—including the route optimizer and prediction service—surpass 90% coverage.")

    # ==========================================================================
    # SLIDE 14: System Limitations & Future Scope
    # ==========================================================================
    s14 = create_base_slide(prs, "System Limitations & Proposed Future Enhancements")

    add_card(s14, 0.8, 1.6, 5.7, 5.2, "Current System Limitations")
    tb = s14.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(5.3), Inches(4.4))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "1. Atmospheric Aerodynamics:\nWind is modeled as a steady horizontal scalar headwind rather than a turbulent 3D micro-climate vector field.\n\n2. Battery Electrochemistry:\nPower discharge is modeled linearly; does not capture ambient temperature effects on LiPo cell voltage sag.\n\n3. Single-Agent Airspace Planning:\nCorridors are calculated independently; does not yet include dynamic multi-agent collision avoidance.\n\n4. Software Simulation Boundary:\nDoes not interface with physical autopilot hardware (PX4/ArduPilot) via MAVLink telemetry."

    add_card(s14, 6.8, 1.6, 5.7, 5.2, "Proposed Future Enhancements")
    tb = s14.shapes.add_textbox(Inches(7.0), Inches(2.2), Inches(5.3), Inches(4.4))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = "1. Hardware-in-the-Loop (HIL) Bridge:\nTranslate generated waypoints into MAVLink mission items for physical drone flight controllers.\n\n2. 4D Airspace Deconfliction:\nIntegrate ADS-B transponder telemetry and spatiotemporal bounding boxes to prevent mid-air multi-drone collisions.\n\n3. Multi-Hop Automated Charging Networks:\nOptimize delivery paths across regional networks featuring automated battery-swap pads and solar charging stations.\n\n4. Real-World Sensor Telemetry Collection:\nCollect empirical UAV flight logs to train non-linear deep learning models on physical aerodynamics."

    set_speaker_notes(s14, "We acknowledge the technical boundaries of our prototype: steady wind assumptions and linear battery models. In future work, we plan to connect this system to physical autopilots via MAVLink, integrate automated battery swapping networks, and implement 4D multi-agent airspace deconfliction.")

    # ==========================================================================
    # SLIDE 15: Conclusion & Summary of Contributions (Dark Navy)
    # ==========================================================================
    s15 = create_base_slide(prs, "", dark_mode=True)
    tb = s15.shapes.add_textbox(Inches(1.2), Inches(1.0), Inches(10.9), Inches(5.5))
    tf = tb.text_frame
    tf.word_wrap = True

    p0 = tf.paragraphs[0]
    p0.text = "FINAL-YEAR B.TECH CAPSTONE PROJECT CONCLUSION"
    p0.font.size = Pt(12)
    p0.font.bold = True
    p0.font.color.rgb = ACCENT_BLUE

    p1 = tf.add_paragraph()
    p1.text = "Summary of Key Engineering Contributions"
    p1.font.size = Pt(28)
    p1.font.bold = True
    p1.font.color.rgb = TEXT_WHITE
    p1.space_before = Pt(8)

    p2 = tf.add_paragraph()
    p2.text = "1. Layered Clean Architecture: Modular, robust Flask 3.1 & SQLAlchemy 2.0 system with 3NF relational schema and defensive security.\n2. Multi-Objective Optimization: Min-max normalized scalarization that prevents unnecessary high-altitude climb energy waste.\n3. Priority-Driven Fleet Allocation: Priority Best-Fit matching delivering 100% high-priority fulfillment under fleet scarcity.\n4. Resilient Dynamic Rerouting: Safety-mandated in-flight hazard evasion with permanent database route preservation.\n5. Rigorous Empirical Verification: 125 automated tests, 83% statement coverage, and 10 genuine captured application screens."
    p2.font.size = Pt(13)
    p2.font.color.rgb = RGBColor(226, 232, 240)
    p2.space_before = Pt(18)

    p3 = tf.add_paragraph()
    p3.text = "THANK YOU!\nWe welcome questions from the examination panel."
    p3.font.size = Pt(18)
    p3.font.bold = True
    p3.font.color.rgb = ACCENT_BLUE
    p3.space_before = Pt(26)

    set_speaker_notes(s15, "In conclusion, our project provides an academically rigorous, verified software solution for emergency medical drone logistics. By combining multi-objective optimization, fail-safe battery and payload checks, priority-driven batch allocation, and dynamic rerouting, the system establishes a robust blueprint for future autonomous delivery research. Thank you. We now welcome questions from the examination panel.")

    prs.save(str(OUTPUT_FILE))
    print(f"[+] Presentation successfully generated at: {OUTPUT_FILE}")
    print(f"[+] Slide Count: {len(prs.slides)} slides.")


if __name__ == "__main__":
    build_presentation()
