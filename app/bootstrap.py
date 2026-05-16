from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.repositories import CarouselRepository, TemplateRepository
from app.services.ai_clients import AnthropicClient, GeminiImageClient
from app.services.carousel_service import CarouselService
from app.services.image_generation import ImageGenerationService
from app.services.linkedin_auth import LinkedInAuthService
from app.services.linkedin_publishing import LinkedInPublishingService
from app.services.orchestrator import CarouselOrchestrator
from app.services.renderer import RenderService
from app.services.template_ingestion import TemplateIngestionService
from app.services.user_profile import UserProfileRepository


@dataclass
class ServiceContainer:
    settings: Settings
    template_repository: TemplateRepository
    carousel_repository: CarouselRepository
    template_ingestion_service: TemplateIngestionService
    carousel_service: CarouselService
    linkedin_auth_service: LinkedInAuthService
    linkedin_publishing_service: LinkedInPublishingService
    user_profile_repository: UserProfileRepository


def build_container() -> ServiceContainer:
    settings = Settings.load()
    template_repository = TemplateRepository(
        builtin_root=settings.builtin_templates_dir,
        import_root=settings.templates_dir,
    )
    carousel_repository = CarouselRepository(settings.carousels_dir)
    user_profile_repository = UserProfileRepository(settings.data_dir / "profiles")
    claude_client = AnthropicClient(
        api_key=settings.claude_api_key,
        model=settings.claude_model,
    )
    gemini_client = GeminiImageClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_image_model,
    )
    image_generation_service = ImageGenerationService(
        settings.artifacts_dir,
        gemini_client=gemini_client,
    )
    render_service = RenderService(settings.artifacts_dir)
    orchestrator = CarouselOrchestrator(claude_client=claude_client)
    template_ingestion_service = TemplateIngestionService(template_repository)
    linkedin_auth_service = LinkedInAuthService(settings)
    linkedin_publishing_service = LinkedInPublishingService(
        settings=settings,
        auth_service=linkedin_auth_service,
    )
    carousel_service = CarouselService(
        template_repository=template_repository,
        carousel_repository=carousel_repository,
        orchestrator=orchestrator,
        image_generation_service=image_generation_service,
        render_service=render_service,
        linkedin_publishing_service=linkedin_publishing_service,
        linkedin_auth_service=linkedin_auth_service,
        user_profile_repository=user_profile_repository,
    )
    return ServiceContainer(
        settings=settings,
        template_repository=template_repository,
        carousel_repository=carousel_repository,
        template_ingestion_service=template_ingestion_service,
        carousel_service=carousel_service,
        linkedin_auth_service=linkedin_auth_service,
        linkedin_publishing_service=linkedin_publishing_service,
        user_profile_repository=user_profile_repository,
    )
