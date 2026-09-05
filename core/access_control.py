from typing import Any, List, Dict

class AccessControl:
    """
    Controller layer for field_mask enforcement (structural least-privilege).
    """
    
    @staticmethod
    def apply_field_mask(data: Dict[str, Any], allowed_fields: List[str]) -> Dict[str, Any]:
        """
        Filters the input data dictionary to only include keys present in allowed_fields.
        """
        masked_data = {}
        for field in allowed_fields:
            if field in data:
                masked_data[field] = data[field]
        return masked_data

    @staticmethod
    def enforce_read_access(user_role: str, entity_data: Dict[str, Any], role_masks: Dict[str, List[str]]) -> Dict[str, Any]:
        """
        Enforces read access by applying the field mask associated with the user's role.
        """
        if user_role not in role_masks:
            raise PermissionError(f"Role '{user_role}' has no defined access rules.")
            
        allowed_fields = role_masks[user_role]
        if allowed_fields == ["*"]:
            return entity_data
            
        return AccessControl.apply_field_mask(entity_data, allowed_fields)

    @staticmethod
    def enforce_write_access(user_role: str, update_data: Dict[str, Any], role_masks: Dict[str, List[str]]) -> bool:
        """
        Checks if the user has permission to write the provided fields based on their role's field mask.
        Returns True if allowed, raises PermissionError otherwise.
        """
        if user_role not in role_masks:
            raise PermissionError(f"Role '{user_role}' has no defined write access rules.")
            
        allowed_fields = role_masks[user_role]
        if allowed_fields == ["*"]:
            return True
            
        for field in update_data.keys():
            if field not in allowed_fields:
                raise PermissionError(f"Role '{user_role}' is not allowed to modify field '{field}'.")
                
        return True
