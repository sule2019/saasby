from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
import json
import os
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from flask import Flask, abort, flash, g, make_response, redirect, render_template, request, url_for
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text


load_dotenv()

db = SQLAlchemy()


def normalize_database_url(database_url: str | None) -> str:
    if not database_url:
        return "sqlite:///saasby.db"
    normalized = database_url.replace("postgres://", "postgresql://", 1)
    if normalized.startswith("postgresql://") and not normalized.startswith("postgresql+psycopg://"):
        normalized = normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgresql://") and "sslmode=" not in normalized:
        separator = "&" if "?" in normalized else "?"
        normalized = f"{normalized}{separator}sslmode=require"
    if normalized.startswith("postgresql+psycopg://") and "sslmode=" not in normalized:
        separator = "&" if "?" in normalized else "?"
        normalized = f"{normalized}{separator}sslmode=require"
    return normalized


def normalize_auth_base_url(value: str | None) -> str:
    if not value:
        return ""
    return value.rstrip("/")


def auth_headers_from_request() -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    cookie = request.headers.get("Cookie")
    if cookie:
        headers["Cookie"] = cookie
    user_agent = request.headers.get("User-Agent")
    if user_agent:
        headers["User-Agent"] = user_agent
    forwarded_for = request.headers.get("X-Forwarded-For") or request.remote_addr
    if forwarded_for:
        headers["X-Forwarded-For"] = forwarded_for
    return headers


def auth_api_request(
    app: Flask,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    include_request_headers: bool = True,
    origin: str | None = None,
) -> tuple[int, dict[str, Any], list[str]]:
    base_url = app.config.get("NEON_AUTH_BASE_URL", "")
    if not base_url:
        raise RuntimeError("NEON_AUTH_BASE_URL is not configured.")

    url = f"{base_url}{path}"
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if include_request_headers:
        headers.update(auth_headers_from_request())
    else:
        headers["Accept"] = "application/json"
    if origin:
        headers["Origin"] = origin
        headers["Referer"] = origin.rstrip("/") + "/"
    req = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read().decode("utf-8", "ignore")
            parsed = json.loads(content) if content else {}
            return response.status, parsed, response.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as exc:
        content = exc.read().decode("utf-8", "ignore")
        try:
            parsed = json.loads(content) if content else {}
        except json.JSONDecodeError:
            parsed = {"message": content or str(exc)}
        return exc.code, parsed, exc.headers.get_all("Set-Cookie") or []


def session_user_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return None
    if isinstance(payload.get("user"), dict):
        return payload["user"]
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("user"), dict):
        return data["user"]
    return None


def session_required() -> Any:
    if g.auth_user is not None:
        return None
    flash("Log in to launch a product.", "info")
    return redirect(url_for("login", next=request.path))


def parse_multiline_list(value: str) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def is_admin_email(email: str | None, app: Flask) -> bool:
    if not email:
        return False
    admins = {
        item.strip().lower()
        for item in app.config.get("ADMIN_EMAILS", "").split(",")
        if item.strip()
    }
    return email.lower() in admins


def admin_required(app: Flask) -> Any:
    result = session_required()
    if result is not None:
        return result
    if not is_admin_email(g.auth_user.get("email"), app):
        abort(403)
    return None


def normalize_listing_detail(listing: Listing) -> dict[str, Any]:
    screenshots = listing.screenshots or []
    if not screenshots and listing.website_url and listing.website_url != "#":
        screenshots = [f"{listing.website_url.rstrip('/')}/og-image"]
    starting_price = listing.starting_price or listing.pricing
    return {
        "short_description": listing.short_description or listing.description,
        "long_description": listing.long_description or " ".join(listing.overview) or listing.description,
        "starting_price": starting_price,
        "demo_url": listing.demo_url,
        "founder_name": listing.founder_name or listing.author,
        "location": listing.location,
        "screenshots": screenshots,
        "what_it_does": listing.what_it_does or listing.overview,
        "who_its_for": listing.who_its_for or [listing.tagline],
        "use_cases": listing.use_cases,
        "pricing_packages": listing.pricing_packages,
    }


class ProductSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    auth_user_id = db.Column(db.String(255), nullable=False, index=True)
    auth_email = db.Column(db.String(255), nullable=False, index=True)
    auth_name = db.Column(db.String(255), nullable=True)
    name = db.Column(db.String(140), nullable=False)
    tagline = db.Column(db.String(220), nullable=False)
    short_description = db.Column(db.String(320), nullable=False)
    long_description = db.Column(db.Text, nullable=False)
    website_url = db.Column(db.String(500), nullable=False)
    demo_url = db.Column(db.String(500), nullable=True)
    github_url = db.Column(db.String(500), nullable=True)
    pricing = db.Column(db.String(40), nullable=False)
    starting_price = db.Column(db.String(120), nullable=True)
    founder_name = db.Column(db.String(255), nullable=True)
    location = db.Column(db.String(255), nullable=True)
    screenshots_text = db.Column(db.Text, nullable=True)
    what_it_does_text = db.Column(db.Text, nullable=False)
    who_its_for_text = db.Column(db.Text, nullable=False)
    features_text = db.Column(db.Text, nullable=False)
    use_cases_text = db.Column(db.Text, nullable=True)
    tags_text = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="pending")
    admin_launch_date = db.Column(db.String(120), nullable=True)
    admin_last_updated = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    packages = db.relationship("ProductSubmissionPackage", backref="submission", cascade="all, delete-orphan")

    @property
    def tags(self) -> list[str]:
        if not self.tags_text:
            return []
        return [tag.strip() for tag in self.tags_text.split(",") if tag.strip()]

    @property
    def screenshots(self) -> list[str]:
        if not self.screenshots_text:
            return []
        return [line.strip() for line in self.screenshots_text.splitlines() if line.strip()]

    @property
    def what_it_does(self) -> list[str]:
        return [line.strip() for line in (self.what_it_does_text or "").splitlines() if line.strip()]

    @property
    def who_its_for(self) -> list[str]:
        return [line.strip() for line in (self.who_its_for_text or "").splitlines() if line.strip()]

    @property
    def features(self) -> list[str]:
        return [line.strip() for line in (self.features_text or "").splitlines() if line.strip()]

    @property
    def use_cases(self) -> list[str]:
        return [line.strip() for line in (self.use_cases_text or "").splitlines() if line.strip()]


class ProductSubmissionPackage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("product_submission.id"), nullable=False, index=True)
    package_name = db.Column(db.String(120), nullable=False)
    package_price = db.Column(db.String(120), nullable=False)
    package_description = db.Column(db.String(255), nullable=True)


def ensure_submission_schema(app: Flask) -> None:
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    if "product_submission" not in tables:
        db.create_all()
        return

    existing_columns = {column["name"] for column in inspector.get_columns("product_submission")}
    product_submission_columns = {
        "short_description": "TEXT",
        "long_description": "TEXT",
        "demo_url": "VARCHAR(500)",
        "github_url": "VARCHAR(500)",
        "starting_price": "VARCHAR(120)",
        "founder_name": "VARCHAR(255)",
        "location": "VARCHAR(255)",
        "screenshots_text": "TEXT",
        "what_it_does_text": "TEXT",
        "who_its_for_text": "TEXT",
        "features_text": "TEXT",
        "use_cases_text": "TEXT",
        "admin_launch_date": "VARCHAR(120)",
        "admin_last_updated": "VARCHAR(120)",
    }

    with db.engine.begin() as connection:
        for column_name, column_type in product_submission_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(f"ALTER TABLE product_submission ADD COLUMN {column_name} {column_type}"))

    if "product_submission_package" not in tables:
        ProductSubmissionPackage.__table__.create(db.engine)


@dataclass(frozen=True)
class Listing:
    slug: str
    logo: str
    name: str
    category: str
    tagline: str
    description: str
    upvotes: int
    downvotes: int
    pricing: str
    license_name: str
    website_url: str
    repo_url: str
    author: str
    updated_at: str
    oss: bool
    tags: list[str]
    features: list[dict[str, str]]
    overview: list[str]
    install_command: str
    config_snippet: str
    tools: list[dict[str, str]]
    discussions: list[dict[str, Any]]
    supported_clients: list[str] = field(default_factory=list)
    auth_model: str = ""
    value_prop: str = ""
    mcp_url: str = ""
    docs: list[dict[str, str]] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)
    faqs: list[dict[str, str]] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    short_description: str = ""
    long_description: str = ""
    starting_price: str = ""
    demo_url: str = ""
    founder_name: str = ""
    location: str = ""
    launch_date: str = ""
    last_updated: str = ""
    screenshots: list[str] = field(default_factory=list)
    what_it_does: list[str] = field(default_factory=list)
    who_its_for: list[str] = field(default_factory=list)
    use_cases: list[str] = field(default_factory=list)
    pricing_packages: list[dict[str, str]] = field(default_factory=list)


LISTINGS: list[Listing] = [
    Listing(
        slug="stripe-mcp-server",
        logo="{ }",
        name="Stripe MCP Server",
        category="MCP Server",
        tagline="Give any model safe access to payments, invoices, and subscriptions.",
        description="A production-ready MCP server that lets AI tools query customers, create payment links, and inspect subscriptions without exposing your full Stripe dashboard.",
        upvotes=268,
        downvotes=14,
        pricing="Free / Open source",
        license_name="MIT License",
        website_url="https://github.com/saasby/stripe-mcp",
        repo_url="https://github.com/saasby/stripe-mcp",
        author="Saasby Labs",
        updated_at="Updated 2 days ago",
        oss=True,
        tags=["payments", "stripe", "mcp", "subscriptions"],
        features=[
            {"title": "Safe account access", "description": "Scope AI access to the Stripe tools you actually want to expose.", "icon": "⌘"},
            {"title": "Checkout workflows", "description": "Create payment links, invoices, and customer records from natural language.", "icon": "◳"},
            {"title": "Developer-friendly install", "description": "Ships with a quick CLI install and a simple config block for MCP clients.", "icon": "✦"},
        ],
        overview=[
            "Stripe MCP Server connects LLM-powered tools to Stripe in a way that feels native for agents and safe for teams.",
            "Use it to inspect customers, create invoices, check subscriptions, and automate revenue workflows without writing a custom connector every time.",
            "It is designed for builders who want a clean bridge between AI systems and billing operations.",
        ],
        install_command="npm install -g @saasby/stripe-mcp",
        config_snippet='''{\n  "mcpServers": {\n    "stripe": {\n      "command": "stripe-mcp",\n      "env": {\n        "STRIPE_SECRET_KEY": "sk_live_xxx"\n      }\n    }\n  }\n}''',
        tools=[
            {"name": "customers.search", "description": "Search Stripe customers by name, email, or metadata."},
            {"name": "invoices.create", "description": "Create draft invoices directly from your MCP client."},
            {"name": "subscriptions.get", "description": "Inspect subscription state and billing history."},
        ],
        discussions=[
            {"author": "Lena", "age": "3h ago", "text": "Has anyone used this with customer support agents yet?", "score": 18, "badge": "Question"},
            {"author": "Marco", "age": "1d ago", "text": "The install was clean. We had it working in Claude Desktop in about ten minutes.", "score": 27, "badge": "Show & tell"},
        ],
        supported_clients=["Claude Desktop", "Cursor", "Windsurf", "Codex", "Any MCP-compatible client"],
        auth_model="Uses a Stripe secret key passed through environment variables. No OAuth flow is required.",
        value_prop="A safe bridge between AI workflows and Stripe actions, without building a custom billing connector from scratch.",
        mcp_url="mcp://stripe-mcp",
        docs=[
            {"title": "Quickstart", "description": "Install the package, add the config block, and verify the server loads in your client."},
            {"title": "Client setup", "description": "Example setup notes for Claude Desktop, Cursor, and hosted MCP runtimes."},
            {"title": "Security model", "description": "How to scope write access, rotate keys, and keep Stripe operations auditable."},
        ],
        examples=[
            {"title": "Customer support handoff", "description": "Let an internal support agent inspect a customer record and check the current subscription state before drafting a reply."},
            {"title": "Billing ops workflow", "description": "Generate a payment link for a new enterprise customer and log the result back into your CRM."},
            {"title": "Collections check", "description": "Ask an agent which invoices are overdue this week and have it summarize the impacted accounts."},
        ],
        faqs=[
            {"question": "Does it support write actions?", "answer": "Yes. You can expose read-only tools or allow actions like invoice creation and payment-link generation depending on your deployment."},
            {"question": "Who is this best for?", "answer": "Teams building AI assistants for support, finance, or revenue operations that already rely on Stripe."},
            {"question": "Can I self-host it?", "answer": "Yes. The server can run locally or inside your own hosted MCP environment as long as the Stripe secret key is available."},
        ],
        permissions=[
            "Read customers, subscriptions, invoices, and payment links",
            "Optional write access for invoice and payment-link creation",
            "Environment-scoped secret key access only",
        ],
        resources=[
            "Stripe customer records",
            "Invoices and subscription state",
            "Payment links and billing metadata",
        ],
    ),
    Listing(
        slug="inbox-triage-agent",
        logo="IT",
        name="Inbox Triage Agent",
        category="AI Agent",
        tagline="An autonomous agent that reads, sorts, and drafts replies across your inbox.",
        description="Prioritize important threads, draft responses, and keep your team focused on the messages that matter.",
        upvotes=312,
        downvotes=8,
        pricing="Freemium",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Northline",
        updated_at="Updated 6 days ago",
        oss=False,
        tags=["email", "agent", "support"],
        features=[
            {"title": "Priority queues", "description": "Sorts urgent messages from newsletters and noise.", "icon": "✦"},
            {"title": "Draft replies", "description": "Writes responses in your preferred voice and structure.", "icon": "◳"},
            {"title": "Team routing", "description": "Assigns email ownership based on category and urgency.", "icon": "⌘"},
        ],
        overview=["Inbox Triage Agent helps teams handle email overload with AI-first routing and drafting."],
        install_command="npx inbox-triage-agent",
        config_snippet='{"provider":"gmail","mode":"assist"}',
        tools=[{"name": "threads.route", "description": "Routes conversations to the right teammate."}],
        discussions=[],
    ),
    Listing(
        slug="fintech-dashboard-kit",
        logo="◳",
        name="Fintech Dashboard Kit",
        category="UI Template",
        tagline="42 polished React screens with charts, tables, and a full design system.",
        description="A ready-to-ship template kit for AI products, fintech dashboards, and internal tools.",
        upvotes=401,
        downvotes=6,
        pricing="$79 one-time",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Frame Foundry",
        updated_at="Updated 1 week ago",
        oss=False,
        tags=["react", "dashboard", "template"],
        features=[
            {"title": "Production-ready layouts", "description": "Dashboard shells, tables, forms, auth flows, and pricing screens.", "icon": "▦"},
            {"title": "Design tokens", "description": "Color, type, spacing, and chart variables already mapped out.", "icon": "◐"},
            {"title": "Built for customization", "description": "Easy to adapt for SaaS, fintech, and data-heavy products.", "icon": "✺"},
        ],
        overview=["Fintech Dashboard Kit gives product teams a tasteful frontend head start."],
        install_command="pnpm create fintech-dashboard-kit",
        config_snippet='{"theme":"light","framework":"react"}',
        tools=[{"name": "templates.export", "description": "Exports production-ready screens."}],
        discussions=[],
    ),
    Listing(
        slug="cold-outreach-pack",
        logo="✦",
        name="Cold Outreach Pack",
        category="Prompt",
        tagline="28 prompts for research, personalization, and follow-ups that convert.",
        description="A prompt set for outbound teams that want better first messages without sounding robotic.",
        upvotes=189,
        downvotes=21,
        pricing="$24",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Open Loops",
        updated_at="Updated 4 days ago",
        oss=False,
        tags=["prompts", "sales", "outreach"],
        features=[
            {"title": "Research prompts", "description": "Quickly extract hooks from websites and LinkedIn profiles.", "icon": "✎"},
            {"title": "Follow-up flows", "description": "Generate follow-up sequences that stay concise.", "icon": "✦"},
            {"title": "Persona variants", "description": "Different prompt variants for founders, SDRs, and agencies.", "icon": "◊"},
        ],
        overview=["Cold Outreach Pack helps builders turn AI into a better outbound writing assistant."],
        install_command="Import prompts into your preferred AI client",
        config_snippet='{"collection":"outreach-pack"}',
        tools=[{"name": "prompt.bundle", "description": "Provides grouped prompts for outreach workflows."}],
        discussions=[],
    ),
    Listing(
        slug="pdf-extractor-skill",
        logo="⌘",
        name="PDF Extractor Skill",
        category="Claude Skill",
        tagline="Teach Claude to parse, structure, and validate PDFs with one reusable skill.",
        description="A workflow skill for invoices, research docs, contracts, and large structured PDFs.",
        upvotes=347,
        downvotes=9,
        pricing="Free",
        license_name="MIT License",
        website_url="#",
        repo_url="#",
        author="Codex Guild",
        updated_at="Updated 5 days ago",
        oss=True,
        tags=["claude", "pdf", "skill"],
        features=[
            {"title": "Structured extraction", "description": "Pulls key fields into a normalized JSON shape.", "icon": "⌘"},
            {"title": "Validation rules", "description": "Check totals, dates, and missing sections automatically.", "icon": "◳"},
            {"title": "Reusable prompt layer", "description": "Keeps your extraction workflow consistent across files.", "icon": "✦"},
        ],
        overview=["PDF Extractor Skill makes document-heavy AI workflows more dependable."],
        install_command="codex skills install pdf-extractor-skill",
        config_snippet='{"input":"invoice.pdf","schema":"invoice-v1"}',
        tools=[{"name": "documents.extract", "description": "Extracts structured content from uploaded PDFs."}],
        discussions=[],
    ),
    Listing(
        slug="blogflow",
        logo="▦",
        name="BlogFlow",
        category="Product",
        tagline="A complete AI content engine you can deploy and run on your own server.",
        description="Drafts outlines, clusters keywords, and manages publishing workflows for growing content teams.",
        upvotes=223,
        downvotes=12,
        pricing="$49/mo",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Atlas Forge",
        updated_at="Updated 8 days ago",
        oss=False,
        tags=["content", "seo", "publishing"],
        features=[
            {"title": "Keyword clustering", "description": "Turn a topic space into a publishing plan.", "icon": "▦"},
            {"title": "Draft generation", "description": "Produces first drafts with editable brand constraints.", "icon": "✺"},
            {"title": "Editorial workflow", "description": "Move from idea to published post in one system.", "icon": "◐"},
        ],
        overview=["BlogFlow combines research, drafting, and editorial operations for AI-assisted content teams."],
        install_command="docker compose up blogflow",
        config_snippet='{"workspace":"content-team"}',
        tools=[{"name": "posts.generate", "description": "Generates outlines and article drafts."}],
        discussions=[],
    ),
    Listing(
        slug="datachat",
        logo="▣",
        name="DataChat",
        category="Product",
        tagline="Chat with your spreadsheets and databases on your own infra.",
        description="A self-hosted analytics workspace that lets teams ask questions across spreadsheets, warehouses, and CSVs using natural language.",
        upvotes=255,
        downvotes=13,
        pricing="$29/mo",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Signal Works",
        updated_at="Updated 1 week ago",
        oss=False,
        tags=["analytics", "sql", "chat"],
        features=[
            {"title": "Warehouse chat", "description": "Ask questions across your SQL data without writing queries.", "icon": "▣"},
            {"title": "Spreadsheet sync", "description": "Pull live sheet and CSV data into one AI-ready view.", "icon": "◳"},
            {"title": "Private deployment", "description": "Run in your own environment with role-based access.", "icon": "✦"},
        ],
        overview=["DataChat helps teams explore internal data with natural language while keeping infrastructure under their control."],
        install_command="docker compose up datachat",
        config_snippet='{"sources":["postgres","csv","sheets"]}',
        tools=[{"name": "queries.ask", "description": "Ask natural-language questions across connected data sources."}],
        discussions=[],
    ),
    Listing(
        slug="launchboard",
        logo="◐",
        name="Launchboard",
        category="Product",
        tagline="A release command center for product, design, and GTM teams.",
        description="Track launches, blockers, tasks, creative assets, and approvals in one place without stitching together six tools.",
        upvotes=211,
        downvotes=9,
        pricing="$39/mo",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Northline",
        updated_at="Updated 3 days ago",
        oss=False,
        tags=["launches", "collaboration", "planning"],
        features=[
            {"title": "Launch timelines", "description": "Map owners, milestones, and dependencies on one track.", "icon": "◐"},
            {"title": "Review threads", "description": "Keep asset approvals and decisions attached to the work.", "icon": "✺"},
            {"title": "Status visibility", "description": "See what is blocked, shipped, or waiting on approval.", "icon": "⌘"},
        ],
        overview=["Launchboard gives growing teams a dedicated surface for coordinating launches and rollout work."],
        install_command="npx launchboard start",
        config_snippet='{"workspace":"launches"}',
        tools=[{"name": "launches.track", "description": "Track cross-functional launches and status."}],
        discussions=[],
    ),
    Listing(
        slug="signaldesk",
        logo="◈",
        name="SignalDesk",
        category="Product",
        tagline="Monitor product metrics, support issues, and launch signals from one workspace.",
        description="A shared operating layer for product, marketing, and support teams that want one place to track what is changing.",
        upvotes=198,
        downvotes=6,
        pricing="$32/mo",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Northline",
        updated_at="Updated 2 days ago",
        oss=False,
        tags=["analytics", "ops", "monitoring"],
        features=[
            {"title": "Unified signal feed", "description": "Bring together launches, tickets, and product health in one view.", "icon": "◐"},
            {"title": "Alert routing", "description": "Send the right updates to the right teams automatically.", "icon": "✦"},
            {"title": "Weekly digests", "description": "Summarize movement across teams without extra reporting work.", "icon": "⌘"},
        ],
        overview=["SignalDesk gives cross-functional teams a calmer way to track product performance and customer signals."],
        install_command="docker compose up signaldesk",
        config_snippet='{"workspace":"growth"}',
        tools=[{"name": "signals.digest", "description": "Builds summaries from connected product and support data."}],
        discussions=[],
    ),
    Listing(
        slug="funnelbase",
        logo="◌",
        name="FunnelBase",
        category="Product",
        tagline="A conversion analytics workspace for signup funnels, onboarding, and trial activation.",
        description="Track where users drop off, compare cohorts, and spot activation wins without hopping between five analytics tools.",
        upvotes=187,
        downvotes=5,
        pricing="$24/mo",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Atlas Forge",
        updated_at="Updated 4 days ago",
        oss=False,
        tags=["growth", "analytics", "saas"],
        features=[
            {"title": "Activation maps", "description": "See what user actions actually correlate with retention.", "icon": "▣"},
            {"title": "Cohort compare", "description": "Compare trial, paid, and churned users side by side.", "icon": "◳"},
            {"title": "Fast setup", "description": "Start with a small event schema and grow from there.", "icon": "✺"},
        ],
        overview=["FunnelBase helps SaaS teams understand where conversion momentum is gained or lost."],
        install_command="npx funnelbase dev",
        config_snippet='{"source":"postgres"}',
        tools=[{"name": "funnels.compare", "description": "Compares conversion performance across user segments."}],
        discussions=[],
    ),
    Listing(
        slug="relaydesk",
        logo="✺",
        name="RelayDesk",
        category="Product",
        tagline="A lightweight customer handoff system for sales, success, and support.",
        description="Keep context moving between teams with shared notes, ownership rules, and cleaner account transitions.",
        upvotes=176,
        downvotes=7,
        pricing="$19/mo",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Signal Works",
        updated_at="Updated 1 day ago",
        oss=False,
        tags=["handoff", "crm", "support"],
        features=[
            {"title": "Shared account context", "description": "Notes, risks, and next steps stay attached to the customer.", "icon": "⌘"},
            {"title": "Owner rules", "description": "Route accounts by segment, urgency, or lifecycle stage.", "icon": "◳"},
            {"title": "Timeline view", "description": "See every touchpoint across teams in one thread.", "icon": "✦"},
        ],
        overview=["RelayDesk helps growing teams stop losing customer context during internal handoffs."],
        install_command="docker compose up relaydesk",
        config_snippet='{"routing":"segment"}',
        tools=[{"name": "handoffs.route", "description": "Routes account ownership and handoff workflows."}],
        discussions=[],
    ),
    Listing(
        slug="brieflane",
        logo="✧",
        name="Brieflane",
        category="Product",
        tagline="Turn ideas, documents, and meeting notes into crisp project briefs.",
        description="A writing-first product planning tool that helps teams move from fuzzy ideas to aligned execution briefs.",
        upvotes=169,
        downvotes=4,
        pricing="$18/mo",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Open Loops",
        updated_at="Updated 5 days ago",
        oss=False,
        tags=["planning", "docs", "product"],
        features=[
            {"title": "Brief generation", "description": "Convert messy inputs into structured project briefs.", "icon": "✎"},
            {"title": "Review loops", "description": "Comment, refine, and approve within one document flow.", "icon": "◊"},
            {"title": "Decision history", "description": "Track why a brief changed over time.", "icon": "✦"},
        ],
        overview=["Brieflane gives teams a faster way to create product briefs that are actually usable."],
        install_command="pnpm brieflane dev",
        config_snippet='{"workspace":"planning"}',
        tools=[{"name": "briefs.create", "description": "Creates structured product briefs from notes and inputs."}],
        discussions=[],
    ),
    Listing(
        slug="chartpilot",
        logo="◍",
        name="ChartPilot",
        category="Product",
        tagline="Generate presentation-ready charts and dashboards from raw business data.",
        description="A reporting product for ops and leadership teams that need cleaner dashboards without a heavy BI rollout.",
        upvotes=161,
        downvotes=5,
        pricing="$29/mo",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Frame Foundry",
        updated_at="Updated 3 days ago",
        oss=False,
        tags=["charts", "reporting", "dashboards"],
        features=[
            {"title": "Executive-ready charts", "description": "Turn raw tables into clean, shareable reporting views.", "icon": "▦"},
            {"title": "Data source sync", "description": "Connect spreadsheets, warehouses, and exports.", "icon": "◐"},
            {"title": "Snapshot exports", "description": "Share branded static views with one click.", "icon": "✺"},
        ],
        overview=["ChartPilot helps teams publish clearer business reporting with far less manual formatting."],
        install_command="docker compose up chartpilot",
        config_snippet='{"sources":["sheets","warehouse"]}',
        tools=[{"name": "charts.publish", "description": "Publishes charts and dashboard snapshots from connected data."}],
        discussions=[],
    ),
    Listing(
        slug="opsatlas",
        logo="⬡",
        name="OpsAtlas",
        category="Product",
        tagline="Map workflows, owners, and dependencies across your internal operations.",
        description="A product for operations-heavy teams that need to see how recurring workflows connect and where they break.",
        upvotes=154,
        downvotes=3,
        pricing="$35/mo",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Codex Guild",
        updated_at="Updated 6 days ago",
        oss=False,
        tags=["operations", "mapping", "workflows"],
        features=[
            {"title": "Workflow maps", "description": "Visualize recurring processes and bottlenecks.", "icon": "▥"},
            {"title": "Ownership layers", "description": "See exactly who owns each stage of execution.", "icon": "◳"},
            {"title": "Failure tracking", "description": "Capture recurring blockers and fix patterns.", "icon": "⌘"},
        ],
        overview=["OpsAtlas gives teams a better map of the internal systems that actually run the business."],
        install_command="npx opsatlas start",
        config_snippet='{"mode":"ops"}',
        tools=[{"name": "ops.map", "description": "Maps workflow stages, dependencies, and owners."}],
        discussions=[],
    ),
    Listing(
        slug="saas-marketing-stack",
        logo="◫",
        name="SaaS Marketing Stack",
        category="UI Template",
        tagline="Landing pages, pricing, docs, and onboarding screens in one kit.",
        description="A polished marketing and onboarding template set for AI startups shipping fast and iterating often.",
        upvotes=286,
        downvotes=7,
        pricing="$59 one-time",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Frame Foundry",
        updated_at="Updated 2 days ago",
        oss=False,
        tags=["marketing", "landing page", "next.js"],
        features=[
            {"title": "Conversion pages", "description": "Hero, pricing, FAQ, testimonials, and feature layouts.", "icon": "◫"},
            {"title": "Onboarding flows", "description": "Signup, invite, workspace setup, and success states.", "icon": "◐"},
            {"title": "Brand-ready system", "description": "Easy to restyle with tokenized spacing and type.", "icon": "✺"},
        ],
        overview=["SaaS Marketing Stack gives teams a cleaner starting point for product marketing and onboarding UI."],
        install_command="pnpm create saas-marketing-stack",
        config_snippet='{"framework":"next","theme":"saas"}',
        tools=[{"name": "templates.export", "description": "Exports web-ready marketing and onboarding screens."}],
        discussions=[],
    ),
    Listing(
        slug="operator-console-kit",
        logo="▥",
        name="Operator Console Kit",
        category="UI Template",
        tagline="Admin panels, audit logs, queue views, and approval workflows.",
        description="A backend operations UI kit built for trust-heavy products that need moderation, review, and visibility.",
        upvotes=174,
        downvotes=5,
        pricing="$69 one-time",
        license_name="Commercial",
        website_url="#",
        repo_url="#",
        author="Northline",
        updated_at="Updated 6 days ago",
        oss=False,
        tags=["admin", "dashboard", "ops"],
        features=[
            {"title": "Review queues", "description": "Moderation lists, approval flows, and audit states.", "icon": "▥"},
            {"title": "Data-dense tables", "description": "Filtering, tags, side panels, and status treatments.", "icon": "◳"},
            {"title": "Internal UX patterns", "description": "Layouts tuned for operator-heavy workflows.", "icon": "⌘"},
        ],
        overview=["Operator Console Kit helps teams ship cleaner internal tooling and operations surfaces."],
        install_command="pnpm create operator-console-kit",
        config_snippet='{"surface":"admin"}',
        tools=[{"name": "templates.export", "description": "Exports internal-tool and admin interface screens."}],
        discussions=[],
    ),
]


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = normalize_database_url(os.environ.get("DATABASE_URL"))
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    app.config["NEON_AUTH_BASE_URL"] = normalize_auth_base_url(os.environ.get("NEON_AUTH_BASE_URL"))
    app.config["APP_BASE_URL"] = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    app.config["ADMIN_EMAILS"] = os.environ.get("ADMIN_EMAILS", "")

    db.init_app(app)

    listing_map = {listing.slug: listing for listing in LISTINGS}
    product_listings = [listing for listing in LISTINGS if listing.category == "Product"]

    def ranked_products() -> list[Listing]:
        return sorted(product_listings, key=lambda item: item.upvotes - item.downvotes, reverse=True)

    @app.cli.command("init-db")
    def init_db_command() -> None:
        with app.app_context():
            db.create_all()
        print("Database initialized.")

    @app.before_request
    def load_neon_auth_session() -> None:
        g.auth_user = None
        g.auth_session = None
        if not app.config["NEON_AUTH_BASE_URL"]:
            return
        try:
            status, payload, _cookies = auth_api_request(app, "GET", "/get-session")
        except RuntimeError:
            return
        if status >= 400:
            return
        g.auth_session = payload
        g.auth_user = session_user_from_payload(payload)

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        nav_items = [
            {
                "label": "Products",
                "href": "/products",
                "icon_svg": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/></svg>',
            },
            {
                "label": "Most Popular This Month",
                "href": "/#most-popular",
                "icon_svg": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3 1.9 5.8H20l-4.9 3.6 1.9 5.8L12 14.6 7 18.2l1.9-5.8L4 8.8h6.1z"/></svg>',
            },
            {
                "label": "Top 100",
                "href": "/top-100",
                "icon_svg": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V10"/><path d="m18 20-6-6-6 6"/><path d="M5 4h14"/></svg>',
            },
            {
                "label": "GitHub",
                "href": "https://github.com/sule2019/saasby",
                "icon_svg": '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .5C5.37.5 0 5.87 0 12.5c0 5.3 3.44 9.8 8.21 11.39.6.11.82-.26.82-.58 0-.29-.01-1.04-.02-2.05-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.09-.75.08-.73.08-.73 1.21.09 1.84 1.24 1.84 1.24 1.07 1.84 2.81 1.31 3.5 1 .11-.78.42-1.31.76-1.61-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 3-.4c1.02 0 2.05.14 3 .4 2.29-1.55 3.3-1.23 3.3-1.23.66 1.66.25 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.49 5.92.43.37.81 1.1.81 2.22 0 1.6-.01 2.89-.01 3.29 0 .32.21.7.83.58A12.01 12.01 0 0 0 24 12.5C24 5.87 18.63.5 12 .5z"/></svg>',
                "external": True,
            },
        ]
        return {
            "nav_items": nav_items,
            "is_admin": is_admin_email((g.auth_user or {}).get("email"), app),
            "app_base_url": app.config["APP_BASE_URL"],
        }

    @app.route("/")
    def home() -> str:
        products = ranked_products()
        return render_template(
            "home.html",
            most_popular=products[:9],
            explore_products=products,
            total_products=len(product_listings),
            nav_cta_label="Launch",
            nav_cta_badge="Free",
            compact_footer=False,
        )

    @app.get("/health")
    def health() -> tuple[dict[str, Any], int]:
        try:
            db.session.execute(text("select 1"))
            database_ok = True
        except Exception:  # noqa: BLE001
            database_ok = False
        return {"ok": True, "database": database_ok}, (200 if database_ok else 503)

    @app.route("/products")
    def products() -> str:
        ranked = ranked_products()
        return render_template(
            "products.html",
            listings=ranked,
            nav_cta_label="Launch",
            nav_cta_badge="Free",
            compact_footer=False,
        )

    @app.route("/signup", methods=["GET", "POST"])
    def signup() -> str:
        if g.auth_user is not None:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            if not app.config["NEON_AUTH_BASE_URL"]:
                flash("Neon Auth is not configured yet. Add NEON_AUTH_BASE_URL first.", "error")
                return redirect(url_for("signup"))
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            name = request.form.get("name", "").strip()

            if not email or "@" not in email:
                flash("Enter a valid email address.", "error")
            elif len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
            elif password != confirm_password:
                flash("Passwords do not match.", "error")
            else:
                status, payload, cookies = auth_api_request(
                    app,
                    "POST",
                    "/sign-up/email",
                    body={
                        "name": name or email.split("@", 1)[0],
                        "email": email,
                        "password": password,
                        "callbackURL": "/dashboard",
                    },
                    include_request_headers=False,
                    origin=app.config["APP_BASE_URL"],
                )
                if status >= 400:
                    flash(payload.get("message") or "Unable to create your account.", "error")
                else:
                    next_url = request.args.get("next") or url_for("dashboard")
                    response = make_response(redirect(next_url))
                    for cookie in cookies:
                        response.headers.add("Set-Cookie", cookie)
                    flash(
                        "Account created. Check your email to verify it before signing in." if not cookies else "Your account is ready.",
                        "success",
                    )
                    return response

        return render_template(
            "auth.html",
            auth_mode="signup",
            nav_cta_label="Launch",
            nav_cta_badge="Free",
            compact_footer=False,
        )

    @app.route("/login", methods=["GET", "POST"])
    def login() -> str:
        if g.auth_user is not None:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            if not app.config["NEON_AUTH_BASE_URL"]:
                flash("Neon Auth is not configured yet. Add NEON_AUTH_BASE_URL first.", "error")
                return redirect(url_for("login"))
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            status, payload, cookies = auth_api_request(
                app,
                "POST",
                "/sign-in/email",
                body={
                    "email": email,
                    "password": password,
                    "rememberMe": True,
                    "callbackURL": "/dashboard",
                },
                include_request_headers=False,
                origin=app.config["APP_BASE_URL"],
            )
            if status >= 400:
                flash(payload.get("message") or "Incorrect email or password.", "error")
            else:
                next_url = request.args.get("next") or url_for("dashboard")
                response = make_response(redirect(next_url))
                for cookie in cookies:
                    response.headers.add("Set-Cookie", cookie)
                flash("Welcome back.", "success")
                return response

        return render_template(
            "auth.html",
            auth_mode="login",
            nav_cta_label="Launch",
            nav_cta_badge="Free",
            compact_footer=False,
        )

    @app.post("/logout")
    def logout() -> Any:
        result = session_required()
        if result is not None:
            return result
        status, payload, cookies = auth_api_request(app, "POST", "/sign-out", body={}, include_request_headers=True)
        response = make_response(redirect(url_for("home")))
        for cookie in cookies:
            response.headers.add("Set-Cookie", cookie)
        flash(payload.get("message") or "You have been logged out.", "success")
        return response

    @app.get("/dashboard")
    def dashboard() -> str:
        result = session_required()
        if result is not None:
            return result
        submissions = (
            ProductSubmission.query.filter_by(auth_user_id=str(g.auth_user.get("id")))
            .order_by(ProductSubmission.created_at.desc())
            .all()
        )
        return render_template(
            "dashboard.html",
            submissions=submissions,
            nav_cta_label="Launch",
            nav_cta_badge="Free",
            compact_footer=False,
        )

    @app.get("/admin")
    def admin_dashboard() -> str:
        result = admin_required(app)
        if result is not None:
            return result
        submissions = ProductSubmission.query.order_by(ProductSubmission.created_at.desc()).all()
        return render_template(
            "admin.html",
            submissions=submissions,
            nav_cta_label="Launch",
            nav_cta_badge="Free",
            compact_footer=False,
        )

    @app.post("/admin/submissions/<int:submission_id>/review")
    def review_submission(submission_id: int) -> Any:
        result = admin_required(app)
        if result is not None:
            return result

        submission = ProductSubmission.query.get_or_404(submission_id)
        status = request.form.get("status", "").strip().lower()
        launch_date = request.form.get("admin_launch_date", "").strip()
        last_updated = request.form.get("admin_last_updated", "").strip()

        if status not in {"pending", "approved", "rejected"}:
            flash("Choose a valid review status.", "error")
            return redirect(url_for("admin_dashboard"))

        submission.status = status
        submission.admin_launch_date = launch_date or None
        submission.admin_last_updated = last_updated or None
        db.session.commit()
        flash(f"{submission.name} updated.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/submit-product")
    def submit_product() -> Any:
        result = session_required()
        if result is not None:
            return result
        name = request.form.get("name", "").strip()
        tagline = request.form.get("tagline", "").strip()
        short_description = request.form.get("short_description", "").strip()
        long_description = request.form.get("long_description", "").strip()
        website_url = request.form.get("website_url", "").strip()
        demo_url = request.form.get("demo_url", "").strip()
        github_url = request.form.get("github_url", "").strip()
        pricing = request.form.get("pricing", "").strip()
        starting_price = request.form.get("starting_price", "").strip()
        founder_name = request.form.get("founder_name", "").strip()
        location = request.form.get("location", "").strip()
        screenshots_text = request.form.get("screenshots_text", "").strip()
        what_it_does_text = request.form.get("what_it_does_text", "").strip()
        who_its_for_text = request.form.get("who_its_for_text", "").strip()
        features_text = request.form.get("features_text", "").strip()
        use_cases_text = request.form.get("use_cases_text", "").strip()
        tags_text = request.form.get("tags", "").strip()
        package_names = request.form.getlist("package_name")
        package_prices = request.form.getlist("package_price")
        package_descriptions = request.form.getlist("package_description")

        errors: list[str] = []
        if not name:
            errors.append("Product name is required.")
        if not tagline:
            errors.append("A short tagline is required.")
        if not short_description:
            errors.append("A short description is required.")
        if not long_description:
            errors.append("A long description is required.")
        if not website_url.startswith("http"):
            errors.append("Enter a valid website URL.")
        if pricing not in {"Free", "Paid", "Freemium"}:
            errors.append("Choose a pricing option.")
        if not what_it_does_text:
            errors.append("Add at least one line for what it does.")
        if not who_its_for_text:
            errors.append("Add at least one line for who it’s for.")
        if not features_text:
            errors.append("Add at least one feature.")

        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(request.referrer or url_for("home"))

        submission = ProductSubmission(
            auth_user_id=str(g.auth_user.get("id")),
            auth_email=g.auth_user.get("email", ""),
            auth_name=g.auth_user.get("name"),
            name=name,
            tagline=tagline,
            short_description=short_description,
            long_description=long_description,
            website_url=website_url,
            demo_url=demo_url or None,
            github_url=github_url or None,
            pricing=pricing,
            starting_price=starting_price or None,
            founder_name=founder_name or None,
            location=location or None,
            screenshots_text=screenshots_text or None,
            what_it_does_text=what_it_does_text,
            who_its_for_text=who_its_for_text,
            features_text=features_text,
            use_cases_text=use_cases_text or None,
            tags_text=tags_text or None,
        )
        for package_name, package_price, package_description in zip(package_names, package_prices, package_descriptions):
            if not package_name.strip() and not package_price.strip() and not package_description.strip():
                continue
            if not package_name.strip() or not package_price.strip():
                flash("Pricing packages need at least a package name and price.", "error")
                return redirect(request.referrer or url_for("home"))
            submission.packages.append(
                ProductSubmissionPackage(
                    package_name=package_name.strip(),
                    package_price=package_price.strip(),
                    package_description=package_description.strip() or None,
                )
            )
        db.session.add(submission)
        db.session.commit()
        flash("Your product has been submitted for review.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/top-100")
    def top_hundred() -> str:
        ranked = ranked_products()
        return render_template(
            "top_100.html",
            listings=ranked[:100],
            nav_cta_label="Launch",
            nav_cta_badge="Free",
            compact_footer=False,
        )

    @app.route("/listing/<slug>")
    def listing_detail(slug: str) -> str:
        def format_link(url: str) -> tuple[str, str]:
            if not url or url == "#":
                return ("Not provided", "")
            return (url.replace("https://", "").replace("http://", ""), url)

        listing = listing_map.get(slug)
        if listing is None or listing.category != "Product":
            abort(404)
        repo_label, repo_href = format_link(listing.repo_url)
        website_label, website_href = format_link(listing.website_url)
        demo_label, demo_href = format_link(listing.demo_url)
        detail_data = normalize_listing_detail(listing)
        quick_facts = [
            {"label": "Price", "value": "Free" if ("free" in listing.pricing.lower()) else "Paid", "href": ""},
            {"label": "Starting price", "value": detail_data["starting_price"], "href": ""},
            {"label": "Founder", "value": detail_data["founder_name"], "href": ""},
            {"label": "Location", "value": detail_data["location"] or "Not provided", "href": ""},
            {"label": "Launch date", "value": listing.launch_date or "Set after approval", "href": ""},
            {"label": "Last updated", "value": listing.last_updated or listing.updated_at, "href": ""},
            {"label": "Website", "value": website_label, "href": website_href},
            {"label": "Demo", "value": demo_label or "Not provided", "href": demo_href},
            {"label": "GitHub", "value": repo_label, "href": repo_href},
        ]
        return render_template(
            "detail.html",
            listing=listing,
            quick_facts=quick_facts,
            is_mcp=False,
            detail_data=detail_data,
            nav_cta_label="Launch",
            nav_cta_badge="Free",
            compact_footer=True,
        )

    with app.app_context():
        if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite") or os.environ.get("AUTO_INIT_DB") == "1":
            db.create_all()
            ensure_submission_schema(app)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
