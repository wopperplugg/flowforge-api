from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

_tracer_provider: TracerProvider | None = None
_sqlalchemy_instrumented = False


def configure_tracing(
    *,
    service_name: str,
    service_version: str,
    deployment_environment: str,
    endpoint: str,
    enabled: bool,
    insecure: bool,
) -> None:
    global _tracer_provider

    if not enabled:
        return
    if _tracer_provider is not None:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment.name": deployment_environment,
        }
    )
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=insecure,
    )

    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer_provider = provider


def instrument_sqlalchemy(
    engine: AsyncEngine,
    *,
    enabled: bool,
) -> None:
    global _sqlalchemy_instrumented

    if not enabled:
        return
    if _sqlalchemy_instrumented:
        return

    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine,
    )
    _sqlalchemy_instrumented = True


def shutdown_tracing() -> None:
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
