from __future__ import annotations

from typing import List

from sdbus import DbusInterfaceCommon, dbus_method, dbus_property


class Scheduler(
    DbusInterfaceCommon,
    interface_name="org.kde.kstars.Ekos.Scheduler",
):
    def __init__(self, *args, **kwargs):
        super(Scheduler, self).__init__(
            service_name="org.kde.kstars",
            object_path="/KStars/Ekos/Scheduler",
            *args,
            **kwargs,
        )

    @dbus_method(method_name="start")
    def start(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="stop")
    def stop(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="removeAllJobs")
    def remove_all_jobs(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="s", result_signature="b", method_name="loadScheduler")
    def load_scheduler(
        self,
        file_u_r_l: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="s", method_name="setSequence")
    def set_sequence(
        self,
        sequence_file_u_r_l: str,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="resetAllJobs")
    def reset_all_jobs(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="profile")
    def profile(self) -> str:
        raise NotImplementedError

    @dbus_property(property_signature="as", property_name="logText")
    def log_text(self) -> List[str]:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="status")
    def status(self) -> int:
        raise NotImplementedError
