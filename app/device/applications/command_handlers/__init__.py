from .device_command_handler import DeviceCommandServiceImpl, IllegalStateError


class DeviceControlCommandServiceImpl:
    def __init__(self, assignment_repo, device_command_repo):
        self.assignment_repo = assignment_repo
        self.device_command_repo = device_command_repo


class DevicePresenceCommandServiceImpl:
    def __init__(self, assignment_repo):
        self.assignment_repo = assignment_repo


class DeviceThresholdCommandServiceImpl:
    def __init__(self, assignment_repo):
        self.assignment_repo = assignment_repo


class OrganizationCommandServiceImpl:
    def __init__(self, organization_repo, space_repo, assignment_repo):
        self.organization_repo = organization_repo
        self.space_repo = space_repo
        self.assignment_repo = assignment_repo


class SpaceCommandServiceImpl:
    def __init__(self, space_repo, organization_repo, assignment_repo):
        self.space_repo = space_repo
        self.organization_repo = organization_repo
        self.assignment_repo = assignment_repo
