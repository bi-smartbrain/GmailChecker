from dotenv import load_dotenv
import os


def get_secrets_path():
    if os.path.exists('../secrets/service_account_freelance.json'):
        return '../secrets'
    elif os.path.exists('/secrets/service_account_freelance.json'):
        return '/secrets'
    else:
        raise FileNotFoundError("secrets not found")


def setup_environment():
    secrets_path = get_secrets_path()
    env_file_path = os.path.join(secrets_path, '.env')
    load_dotenv(env_file_path)
    return secrets_path


SECRETS_PATH = setup_environment()
