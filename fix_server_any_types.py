#!/usr/bin/env python3
"""
Replace all Promise<any> types in server.ts with proper types from api.types.ts
"""

import re

# Mapping of function names to their proper return types
type_mappings = {
    # Users API
    'getCurrentUser': 'User',

    # Admin Users
    'getUsers': 'UsersPage',
    'getUser': 'User',
    'getStatistics': 'UserStatistics',

    # Pipeline
    'getConsultationStatuses': 'ConsultationStatus[]',
    'getPipelineStages': 'PipelineStage[]',
    'getFullPipeline': 'PipelineWithStages',

    # Organization
    'getUnitsTree': 'OrganizationUnit[]',
    'getUnit': 'OrganizationUnit',
    'getTreeWithAggregation': 'OrganizationTreeWithAggregation[]',
    'getMajorPrograms': 'MajorProgram[]',
    'getProgramOfferings': 'ProgramOffering[]',

    # Notifications
    'getTemplates': 'NotificationTemplatesPage',
    'getRules': 'NotificationRulesPage',
    'getEventGroups': 'EventGroup[]',

    # Config
    'getAssignmentConfig': 'AssignmentConfig',
    'getDegreeLevels': 'DegreeLevel[]',
    'getOfferingTypes': 'OfferingType[]',
    'getDocumentTypes': 'DocumentType[]',

    # Distribution
    'getPolicies': 'TuitionDiscountPoliciesPage',
    'getDistributionStats': 'DistributionStats',
    'getRules': 'DistributionRule[]',

    # Permissions
    'getStatistics': 'PermissionStatistics',

    # Notifications (user-facing)
    'getNotifications': 'NotificationsPage',
    'getPreferences': 'NotificationPreferences',
    'getEventGroupPreferences': 'EventGroup[]',

    # Sessions
    'getActiveSessions': 'ActiveSession[]',
}

def fix_server_ts():
    file_path = '/home/user/QLTS/frontend/src/lib/api/server.ts'

    with open(file_path, 'r') as f:
        content = f.read()

    # Remove all eslint-disable-next-line comments for no-explicit-any
    content = re.sub(
        r'\s*// eslint-disable-next-line @typescript-eslint/no-explicit-any\n',
        '',
        content
    )

    # Replace Promise<any> with proper types
    lines = content.split('\n')
    new_lines = []

    for i, line in enumerate(lines):
        new_line = line

        # Check if this line contains Promise<any>
        if 'Promise<any>' in line or 'serverFetch<any>' in line:
            # Extract function name from previous lines
            for j in range(max(0, i-5), i+1):
                func_match = re.search(r'async (\w+)\(', lines[j])
                if func_match:
                    func_name = func_match.group(1)

                    # Find the proper type
                    if func_name in type_mappings:
                        proper_type = type_mappings[func_name]

                        # Replace Promise<any> and serverFetch<any>
                        new_line = new_line.replace('Promise<any>', f'Promise<{proper_type}>')
                        new_line = new_line.replace('serverFetch<any>', f'serverFetch<{proper_type}>')
                        break

        new_lines.append(new_line)

    # Write back
    with open(file_path, 'w') as f:
        f.write('\n'.join(new_lines))

    print("✅ Fixed all Promise<any> types in server.ts!")
    print(f"   Removed eslint-disable comments")
    print(f"   Replaced {len(type_mappings)} function return types")

if __name__ == '__main__':
    fix_server_ts()
