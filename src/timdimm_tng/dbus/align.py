from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sdbus import DbusInterfaceCommon, dbus_method, dbus_property


class Align(
    DbusInterfaceCommon,
    interface_name="org.kde.kstars.Ekos.Align",
):
    def __init__(self, *args, **kwargs):
        super(Align, self).__init__(
            service_name="org.kde.kstars",
            object_path="/KStars/Ekos/Align",
            *args,
            **kwargs,
        )

    @dbus_method(method_name="abort")
    def abort(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(result_signature="b", method_name="captureAndSolve")
    def capture_and_solve(
        self,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="s", result_signature="b", method_name="loadAndSlew")
    def load_and_slew(
        self,
        file_u_r_l: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(input_signature="u", method_name="setSolverMode")
    def set_solver_mode(
        self,
        mode: int,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="i", method_name="setSolverAction")
    def set_solver_action(
        self,
        mode: int,
    ) -> None:
        raise NotImplementedError

    @dbus_method(result_signature="ad", method_name="cameraInfo")
    def camera_info(
        self,
    ) -> List[float]:
        raise NotImplementedError

    @dbus_method(result_signature="ad", method_name="getSolutionResult")
    def get_solution_result(
        self,
    ) -> List[float]:
        raise NotImplementedError

    @dbus_method(result_signature="ad", method_name="telescopeInfo")
    def telescope_info(
        self,
    ) -> List[float]:
        raise NotImplementedError

    @dbus_method(result_signature="i", method_name="getLoadAndSlewStatus")
    def get_load_and_slew_status(
        self,
    ) -> int:
        raise NotImplementedError

    @dbus_method(input_signature="i", method_name="setBinningIndex")
    def set_binning_index(
        self,
        binning_index: int,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="dd", method_name="setTargetCoords")
    def set_target_coords(
        self,
        ra: float,
        de: float,
    ) -> None:
        raise NotImplementedError

    @dbus_method(result_signature="ad", method_name="getTargetCoords")
    def get_target_coords(
        self,
    ) -> List[float]:
        raise NotImplementedError

    @dbus_method(input_signature="d", method_name="setTargetPositionAngle")
    def set_target_position_angle(
        self,
        value: float,
    ) -> None:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="opticalTrain")
    def optical_train(self) -> str:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="camera")
    def camera(self) -> str:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="filterWheel")
    def filter_wheel(self) -> str:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="filter")
    def filter(self) -> str:
        raise NotImplementedError

    @dbus_property(property_signature="as", property_name="logText")
    def log_text(self) -> List[str]:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="status")
    def status(self) -> int:
        raise NotImplementedError

    @dbus_property(property_signature="ad", property_name="fov")
    def fov(self) -> List[float]:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="solverArguments")
    def solver_arguments(self) -> str:
        raise NotImplementedError
