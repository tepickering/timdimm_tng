from __future__ import annotations

from typing import List

from sdbus import (
    DbusInterfaceCommon,
    dbus_method,
    dbus_property,
)


class Capture(
    DbusInterfaceCommon,
    interface_name="org.kde.kstars.Ekos.Capture",
):
    def __init__(self, *args, **kwargs):
        super(Capture, self).__init__(
            service_name="org.kde.kstars",
            object_path="/KStars/Ekos/Capture",
            *args,
            **kwargs,
        )

    @dbus_method(method_name="start")
    def start(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="abort")
    def abort(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="suspend")
    def suspend(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="stop")
    def stop(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="pause")
    def pause(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="toggleSequence")
    def toggle_sequence(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="s", method_name="restartCamera")
    def restart_camera(
        self,
        name: str,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="b", method_name="toggleVideo")
    def toggle_video(
        self,
        enabled: bool,
    ) -> None:
        raise NotImplementedError

    @dbus_method(
        input_signature="sb", result_signature="b", method_name="loadSequenceQueue"
    )
    def load_sequence_queue(
        self,
        file_u_r_l: str,
        ignore_target: bool,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(
        input_signature="s", result_signature="b", method_name="saveSequenceQueue"
    )
    def save_sequence_queue(
        self,
        path: str,
    ) -> bool:
        raise NotImplementedError

    @dbus_method(method_name="clearSequenceQueue")
    def clear_sequence_queue(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(result_signature="s", method_name="getSequenceQueueStatus")
    def get_sequence_queue_status(
        self,
    ) -> str:
        raise NotImplementedError

    @dbus_method(input_signature="bd", method_name="setMaximumGuidingDeviation")
    def set_maximum_guiding_deviation(
        self,
        enable: bool,
        value: float,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="bd", method_name="setInSequenceFocus")
    def set_in_sequence_focus(
        self,
        enable: bool,
        h_f_r: float,
    ) -> None:
        raise NotImplementedError

    @dbus_method(result_signature="i", method_name="getJobCount")
    def get_job_count(
        self,
    ) -> int:
        raise NotImplementedError

    @dbus_method(result_signature="i", method_name="getPendingJobCount")
    def get_pending_job_count(
        self,
    ) -> int:
        raise NotImplementedError

    @dbus_method(input_signature="i", result_signature="s", method_name="getJobState")
    def get_job_state(
        self,
        id: int,
    ) -> str:
        raise NotImplementedError

    @dbus_method(
        input_signature="i", result_signature="s", method_name="getJobFilterName"
    )
    def get_job_filter_name(
        self,
        id: int,
    ) -> str:
        raise NotImplementedError

    @dbus_method(
        input_signature="i", result_signature="i", method_name="getJobImageProgress"
    )
    def get_job_image_progress(
        self,
        id: int,
    ) -> int:
        raise NotImplementedError

    @dbus_method(
        input_signature="i", result_signature="i", method_name="getJobImageCount"
    )
    def get_job_image_count(
        self,
        id: int,
    ) -> int:
        raise NotImplementedError

    @dbus_method(
        input_signature="i", result_signature="d", method_name="getJobExposureProgress"
    )
    def get_job_exposure_progress(
        self,
        id: int,
    ) -> float:
        raise NotImplementedError

    @dbus_method(
        input_signature="i", result_signature="d", method_name="getJobExposureDuration"
    )
    def get_job_exposure_duration(
        self,
        id: int,
    ) -> float:
        raise NotImplementedError

    @dbus_method(
        input_signature="i", result_signature="i", method_name="getJobFrameType"
    )
    def get_job_frame_type(
        self,
        id: int,
    ) -> int:
        raise NotImplementedError

    @dbus_method(result_signature="d", method_name="getProgressPercentage")
    def get_progress_percentage(
        self,
    ) -> float:
        raise NotImplementedError

    @dbus_method(result_signature="i", method_name="getActiveJobID")
    def get_active_job_id(
        self,
    ) -> int:
        raise NotImplementedError

    @dbus_method(result_signature="i", method_name="getActiveJobRemainingTime")
    def get_active_job_remaining_time(
        self,
    ) -> int:
        raise NotImplementedError

    @dbus_method(result_signature="i", method_name="getOverallRemainingTime")
    def get_overall_remaining_time(
        self,
    ) -> int:
        raise NotImplementedError

    @dbus_method(method_name="clearAutoFocusHFR")
    def clear_auto_focus_h_f_r(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(method_name="ignoreSequenceHistory")
    def ignore_sequence_history(
        self,
    ) -> None:
        raise NotImplementedError

    @dbus_method(input_signature="si", method_name="setCapturedFramesMap")
    def set_captured_frames_map(
        self,
        signature: str,
        count: int,
    ) -> None:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="targetName")
    def target_name(self) -> str:
        raise NotImplementedError

    @dbus_property(property_signature="s", property_name="observerName")
    def observer_name(self) -> str:
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

    @dbus_property(property_signature="b", property_name="coolerControl")
    def cooler_control(self) -> bool:
        raise NotImplementedError

    @dbus_property(property_signature="as", property_name="logText")
    def log_text(self) -> List[str]:
        raise NotImplementedError

    @dbus_property(property_signature="i", property_name="status")
    def status(self) -> int:
        raise NotImplementedError
