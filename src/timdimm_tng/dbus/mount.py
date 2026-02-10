from __future__ import annotations

from typing import List

from sdbus import DbusInterfaceCommon, dbus_method, dbus_property


class Mount(
    DbusInterfaceCommon,
    interface_name="org.kde.kstars.Ekos.Mount",
):
    def __init__(self, *args, **kwargs):
        super(Mount, self).__init__(
            service_name="org.kde.kstars",
            object_path="/KStars/Ekos/Mount",
            *args,
            **kwargs,
        )

    @dbus_method(input_signature="dd", result_signature="b", method_name="slew")
    def slew(
        self,
        r_a: float,
        d_e_c: float,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="s", result_signature="b", method_name="gotoTarget")
    def goto_target(
        self,
        target: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="s", result_signature="b", method_name="syncTarget")
    def sync_target(
        self,
        target: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="abort")
    def abort(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="park")
    def park(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="unpark")
    def unpark(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="resetModel")
    def reset_model(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="bd", method_name="setMeridianFlipValues")
    def set_meridian_flip_values(
        self,
        activate: bool,
        hours: float,
    ) -> None:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="opticalTrain")
    def optical_train(self) -> str:
        raise NotImplementedError

    @dbus_property(property_signature="as", property_name="logText")
    def log_text(self) -> List[str]:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="canPark")
    def can_park(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="slewStatus")
    def slew_status(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="ad", property_name="altitudeLimits")
    def altitude_limits(self) -> List[float]:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="altitudeLimitsEnabled")
    def altitude_limits_enabled(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="d", property_name="hourAngleLimit")
    def hour_angle_limit(self) -> float:
        raise NotImplementedError

    @dbus_property(property_signature="b", property_name="hourAngleLimitEnabled")
    def hour_angle_limit_enabled(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="ad", property_name="equatorialCoords")
    def equatorial_coords(self) -> List[float]:
        raise NotImplementedError

    @dbus_property(property_signature="ad", property_name="horizontalCoords")
    def horizontal_coords(self) -> List[float]:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="slewRate")
    def slew_rate(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="d", property_name="hourAngle")
    def hour_angle(self) -> float:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="status")
    def status(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="parkStatus")
    def park_status(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="pierSide")
    def pier_side(self) -> int:
        raise NotImplementedError
