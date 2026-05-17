from . import process
from . import media
from . import history
from . import tools

def register_routes(app):
    app.register_blueprint(process.bp)
    app.register_blueprint(media.bp)
    app.register_blueprint(history.bp)
    app.register_blueprint(tools.bp)
