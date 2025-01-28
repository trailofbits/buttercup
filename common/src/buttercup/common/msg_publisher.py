from buttercup.common.logger import setup_logging
from buttercup.common.queues import QueueFactory, QueueNames
from redis import Redis
from pydantic_settings import BaseSettings, CliSubCommand, CliPositionalArg, get_subcommand
from pydantic import BaseModel
from typing import Annotated
from pydantic import Field
from pathlib import Path
from google.protobuf.text_format import Parse


def get_queue_names():
    return [f"'{queue_name.value}'" for queue_name in QueueNames]


class SendSettings(BaseModel):
    queue_name: CliPositionalArg[str] = Field(description="Queue name (one of " + ", ".join(get_queue_names()) + ")")
    msg_path: CliPositionalArg[Path] = Field(description="Path to message file in Protobuf text format")

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class ListSettings(BaseModel):
    pass

    class Config:
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"


class Settings(BaseSettings):
    redis_url: Annotated[str, Field(default="redis://localhost:6379", description="Redis URL")]
    log_level: Annotated[str, Field(default="info", description="Log level")]
    send: CliSubCommand[SendSettings]
    list: CliSubCommand[ListSettings]

    class Config:
        env_prefix = "BUTTERCUP_MSG_PUBLISHER_"
        env_file = ".env"
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"


def main():
    settings = Settings()
    logger = setup_logging(__name__, settings.log_level)

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    command = get_subcommand(settings)
    if isinstance(command, SendSettings):
        try:
            queue = QueueFactory(redis).create(command.queue_name)
        except Exception as e:
            logger.exception(f"Failed to create queue: {e}")
            return

        msg_builder = queue.msg_builder
        logger.info(f"Reading {msg_builder().__class__.__name__} message from file '{command.msg_path}'")
        msg = Parse(command.msg_path.read_text(), msg_builder())
        logger.info(f"Pushing message to queue '{command.queue_name}': {msg}")
        queue.push(msg)
    elif isinstance(command, ListSettings):
        print("\n".join([f"- {name.value}" for name in QueueNames]))


if __name__ == "__main__":
    main()
