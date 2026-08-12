from typing import Any, AsyncIterator, Protocol, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)


class Message:
    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


def to_langchain_messages(messages: list[Message]) -> list[BaseMessage]:
    result: list[BaseMessage] = []
    for m in messages:
        if m.role == "system":
            result.append(SystemMessage(content=m.content))
        elif m.role == "assistant":
            result.append(AIMessage(content=m.content))
        else:
            result.append(HumanMessage(content=m.content))
    return result


class LLMProvider(Protocol):
    @property
    def model(self) -> BaseChatModel: ...

    async def complete(
        self,
        messages: list[Message],
        *,
        response_format: type[T] | None = None,
    ) -> str | T: ...

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]: ...


class LangChainLLMProvider:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    @property
    def model(self) -> BaseChatModel:
        return self._model

    async def complete(
        self,
        messages: list[Message],
        *,
        response_format: type[T] | None = None,
    ) -> str | T:
        lc_messages = to_langchain_messages(messages)
        if response_format is not None:
            # Groq openai/gpt-oss-* supports strict structured outputs; requires
            # schemas without free-form objects (additionalProperties must be false).
            structured_kwargs: dict[str, Any] = {}
            if settings.llm_provider.lower() == "groq":
                structured_kwargs = {"method": "json_schema", "strict": True}
            structured = self._model.with_structured_output(
                response_format, **structured_kwargs
            )
            result = await structured.ainvoke(lc_messages)
            return result
        response = await self._model.ainvoke(lc_messages)
        return str(response.content)

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        lc_messages = to_langchain_messages(messages)
        async for chunk in self._model.astream(lc_messages):
            if chunk.content:
                yield str(chunk.content)


def get_llm_provider() -> LangChainLLMProvider:
    provider = settings.llm_provider.lower()
    if provider == "groq":
        from langchain_openai import ChatOpenAI

        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        # Groq exposes an OpenAI-compatible API
        model = ChatOpenAI(
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
            model=settings.groq_model,
            temperature=0,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        model = ChatAnthropic(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            temperature=0,
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        model = ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=0,
        )
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}. Use groq, openai, or anthropic.")
    return LangChainLLMProvider(model)
