"""API package — registers all API blueprints with the Flask app."""

from pi_cowork.api.workflows import workflows_bp
from pi_cowork.api.boards import boards_bp
from pi_cowork.api.tickets import tickets_bp
from pi_cowork.api.comments import comments_bp
from pi_cowork.api.questions import questions_bp
from pi_cowork.api.labels import labels_bp
from pi_cowork.api.agents_api import agents_api_bp
from pi_cowork.api.statuses import statuses_bp
from pi_cowork.api.transitions import transitions_bp
from pi_cowork.api.quality_gates import quality_gates_bp
from pi_cowork.api.gate_reviews import gate_reviews_bp
from pi_cowork.api.agent_runs import agent_runs_bp
from pi_cowork.api.notifications import notifications_bp
from pi_cowork.api.settings import settings_bp
from pi_cowork.api.import_export import import_export_bp
from pi_cowork.api.system_logs import system_logs_bp
from pi_cowork.api.events import events_bp
from pi_cowork.api.recurring import recurring_bp
from pi_cowork.api.endpoint_registry import endpoint_registry_bp
from pi_cowork.api.pi_models import pi_models_bp


ALL_BLUEPRINTS = [
    workflows_bp,
    boards_bp,
    tickets_bp,
    comments_bp,
    questions_bp,
    labels_bp,
    agents_api_bp,
    statuses_bp,
    transitions_bp,
    quality_gates_bp,
    gate_reviews_bp,
    agent_runs_bp,
    notifications_bp,
    settings_bp,
    import_export_bp,
    system_logs_bp,
    events_bp,
    recurring_bp,
    endpoint_registry_bp,
    pi_models_bp,
]


def register_api_blueprints(app):
    """Register all API blueprints on the given Flask app."""
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)