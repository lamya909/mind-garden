from app import create_app

# Entry point for local development and production WSGI servers.
app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
