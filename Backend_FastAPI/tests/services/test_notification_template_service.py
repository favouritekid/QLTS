# tests/services/test_notification_template_service.py
"""
Integration tests for NotificationTemplateService.

Covers template CRUD operations, duplicate checks, and system template protection.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.services import notification_template_service
from app.utils.exceptions import BadRequest, PermissionDeniedError, ResourceNotFoundError


@pytest.mark.asyncio
@pytest.mark.integration
class TestNotificationTemplateService:
    """Integration tests for notification_template_service."""

    # =========================================================================
    # GET TEMPLATE BY ID
    # =========================================================================

    async def test_get_template_by_id_success(self, db: AsyncSession):
        """Should return template for valid ID."""
        # Arrange
        template = models.NotificationTemplate(
            template_code="TPL_SVC_GET_1",
            name="Service Get Test",
            title_template="Title",
            message_template="Message"
        )
        db.add(template)
        await db.commit()
        
        # Act
        result = await notification_template_service.get_template_by_id(db, template.id)
        
        # Assert
        assert result.template_code == "TPL_SVC_GET_1"

    async def test_get_template_by_id_not_found(self, db: AsyncSession):
        """Should raise ResourceNotFoundError for invalid ID."""
        with pytest.raises(ResourceNotFoundError):
            await notification_template_service.get_template_by_id(db, 99999)

    # =========================================================================
    # CREATE TEMPLATE - DUPLICATE NAME CHECK
    # =========================================================================

    async def test_create_template_success(
        self, 
        db: AsyncSession,
        admin_user_in_db: dict
    ):
        """Should create template with valid data."""
        # Arrange
        template_data = schemas.NotificationTemplateCreate(
            template_code="TPL_CREATE_SUCCESS",
            name="Create Success Template",
            title_template="Hello ${name}",
            message_template="Welcome to our platform, ${name}!",
            category="onboarding"
        )
        
        # Act
        result, callback = await notification_template_service.create_template(
            db, template_data, admin_user_in_db["id"]
        )
        await db.commit()
        await callback()
        
        # Assert
        assert result.id is not None
        assert result.template_code == "TPL_CREATE_SUCCESS"
        assert result.created_by == admin_user_in_db["id"]

    async def test_create_template_duplicate_name(
        self, 
        db: AsyncSession,
        admin_user_in_db: dict
    ):
        """Should raise BadRequest for duplicate template name."""
        # Arrange - Create existing template
        existing = models.NotificationTemplate(
            template_code="TPL_EXISTING_1",
            name="Duplicate Name Template",
            title_template="Title",
            message_template="Message"
        )
        db.add(existing)
        await db.commit()
        
        # Act & Assert
        template_data = schemas.NotificationTemplateCreate(
            template_code="TPL_NEW_CODE",
            name="Duplicate Name Template",  # Same name
            title_template="Title",
            message_template="Message"
        )
        
        with pytest.raises(BadRequest) as exc_info:
            await notification_template_service.create_template(
                db, template_data, admin_user_in_db["id"]
            )
        
        assert "already exists" in str(exc_info.value.detail)

    async def test_create_template_duplicate_code(
        self, 
        db: AsyncSession,
        admin_user_in_db: dict
    ):
        """Should raise BadRequest for duplicate template_code."""
        # Arrange - Create existing template
        existing = models.NotificationTemplate(
            template_code="TPL_DUPLICATE_CODE_1",
            name="Original Template",
            title_template="Title",
            message_template="Message"
        )
        db.add(existing)
        await db.commit()
        
        # Act & Assert
        template_data = schemas.NotificationTemplateCreate(
            template_code="TPL_DUPLICATE_CODE_1",  # Same code
            name="Different Name",
            title_template="Title",
            message_template="Message"
        )
        
        with pytest.raises(BadRequest) as exc_info:
            await notification_template_service.create_template(
                db, template_data, admin_user_in_db["id"]
            )
        
        assert "already exists" in str(exc_info.value.detail)

    # =========================================================================
    # UPDATE TEMPLATE - DUPLICATE NAME CHECK
    # =========================================================================

    async def test_update_template_success(self, db: AsyncSession):
        """Should update template fields."""
        # Arrange
        template = models.NotificationTemplate(
            template_code="TPL_UPDATE_1",
            name="Original Name",
            title_template="Original Title",
            message_template="Original Message"
        )
        db.add(template)
        await db.commit()
        
        # Act
        update_data = schemas.NotificationTemplateUpdate(
            title_template="Updated Title"
        )
        result, callback = await notification_template_service.update_template(
            db, template, update_data
        )
        await db.commit()
        await callback()
        
        # Assert
        assert result.title_template == "Updated Title"
        assert result.name == "Original Name"  # Unchanged

    async def test_update_template_duplicate_name(self, db: AsyncSession):
        """Should raise BadRequest when updating to existing name."""
        # Arrange - Create two templates
        template1 = models.NotificationTemplate(
            template_code="TPL_UPDATE_DUP_1",
            name="First Template",
            title_template="Title",
            message_template="Message"
        )
        template2 = models.NotificationTemplate(
            template_code="TPL_UPDATE_DUP_2",
            name="Second Template",
            title_template="Title",
            message_template="Message"
        )
        db.add_all([template1, template2])
        await db.commit()
        
        # Act & Assert - Try to rename template2 to template1's name
        update_data = schemas.NotificationTemplateUpdate(name="First Template")
        
        with pytest.raises(BadRequest) as exc_info:
            await notification_template_service.update_template(db, template2, update_data)
        
        assert "already exists" in str(exc_info.value.detail)

    # =========================================================================
    # DELETE TEMPLATE - SYSTEM PROTECTION
    # =========================================================================

    async def test_delete_template_success(self, db: AsyncSession):
        """Should delete non-system template with zero usage."""
        # Arrange
        template = models.NotificationTemplate(
            template_code="TPL_DELETE_1",
            name="Deletable Template",
            title_template="Title",
            message_template="Message",
            is_system=False,
            usage_count=0
        )
        db.add(template)
        await db.commit()
        template_id = template.id
        
        # Act
        result, callback = await notification_template_service.delete_template(db, template)
        await db.commit()
        await callback()
        
        # Assert
        deleted = await db.get(models.NotificationTemplate, template_id)
        assert deleted is None

    async def test_delete_template_system_protected(self, db: AsyncSession):
        """Should raise PermissionDeniedError for system template."""
        # Arrange
        template = models.NotificationTemplate(
            template_code="TPL_SYSTEM_DELETE",
            name="System Template",
            title_template="Title",
            message_template="Message",
            is_system=True
        )
        db.add(template)
        await db.commit()
        
        # Act & Assert
        with pytest.raises(PermissionDeniedError) as exc_info:
            await notification_template_service.delete_template(db, template)
        
        assert "Cannot delete system template" in str(exc_info.value.detail)

    async def test_delete_template_in_use(self, db: AsyncSession):
        """Should raise BadRequest when template has active usage."""
        # Arrange
        template = models.NotificationTemplate(
            template_code="TPL_IN_USE",
            name="In Use Template",
            title_template="Title",
            message_template="Message",
            is_system=False,
            usage_count=3  # Has 3 rules using it
        )
        db.add(template)
        await db.commit()
        
        # Act & Assert
        with pytest.raises(BadRequest) as exc_info:
            await notification_template_service.delete_template(db, template)
        
        assert "currently used by" in str(exc_info.value.detail)

    # =========================================================================
    # GET TEMPLATES - PAGINATION & FILTERS
    # =========================================================================

    async def test_get_templates_pagination(self, db: AsyncSession):
        """Should return paginated results."""
        # Arrange - Create templates
        for i in range(5):
            template = models.NotificationTemplate(
                template_code=f"TPL_PAGE_{i}",
                name=f"Page Template {i}",
                title_template="Title",
                message_template="Message"
            )
            db.add(template)
        await db.commit()
        
        # Act
        templates, total = await notification_template_service.get_templates(
            db, skip=0, limit=3
        )
        
        # Assert
        assert len(templates) <= 3
        assert total >= 5

    async def test_get_templates_with_filters(self, db: AsyncSession):
        """Should apply category and is_system filters."""
        # Arrange
        template = models.NotificationTemplate(
            template_code="TPL_FILTERED_SVC",
            name="Filtered Service Template",
            title_template="Title",
            message_template="Message",
            category="special_category",
            is_system=True
        )
        db.add(template)
        await db.commit()
        
        # Act
        templates, total = await notification_template_service.get_templates(
            db, 
            category="special_category",
            is_system=True
        )
        
        # Assert
        assert total >= 1
        assert any(t.template_code == "TPL_FILTERED_SVC" for t in templates)
