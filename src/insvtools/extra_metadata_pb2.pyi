from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ExtraMetadata(_message.Message):
    __slots__ = ("SerialNumber", "CameraType", "FwVersion", "Offset", "CreationTime", "FileSize", "TotalTime", "Gps", "Gyro", "OriginalOffset", "TriggerSource", "Dimension", "FrameRate", "GammaMode", "FirstFrameTimestamp", "RollingShutterTime", "FileGroupInfo", "WindowCropInfo", "GyroTimestamp", "IsHasGyroTimestamp", "TimelapseInterval", "GyroCalib", "FirstGpsTimestamp", "IsSelfie", "IsFlowstateOnline", "IsDewarp", "ResolutionSize", "BatteryType", "CamPosture", "FovType", "Distance", "Fov", "GyroFilterType", "GyroType", "OffsetV2", "OffsetV3", "OriginalOffsetV2", "OriginalOffsetV3", "FocusSensor", "ExpectOutputType", "AudioMode", "IsRawGyro", "RawCaptureType", "PtsType", "GyroCfgInfo")
    class LogoTypeEnum(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        UNKNOWN_LOGO_TYPE: _ClassVar[ExtraMetadata.LogoTypeEnum]
        NO_LOGO: _ClassVar[ExtraMetadata.LogoTypeEnum]
        INSTA_LOGO: _ClassVar[ExtraMetadata.LogoTypeEnum]
    UNKNOWN_LOGO_TYPE: ExtraMetadata.LogoTypeEnum
    NO_LOGO: ExtraMetadata.LogoTypeEnum
    INSTA_LOGO: ExtraMetadata.LogoTypeEnum
    class TriggerSourceEnum(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        Unknown: _ClassVar[ExtraMetadata.TriggerSourceEnum]
        CameraButton: _ClassVar[ExtraMetadata.TriggerSourceEnum]
        RemoteControl: _ClassVar[ExtraMetadata.TriggerSourceEnum]
        USB: _ClassVar[ExtraMetadata.TriggerSourceEnum]
        BtRemote: _ClassVar[ExtraMetadata.TriggerSourceEnum]
    Unknown: ExtraMetadata.TriggerSourceEnum
    CameraButton: ExtraMetadata.TriggerSourceEnum
    RemoteControl: ExtraMetadata.TriggerSourceEnum
    USB: ExtraMetadata.TriggerSourceEnum
    BtRemote: ExtraMetadata.TriggerSourceEnum
    class BatteryTypeEnum(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        THICK: _ClassVar[ExtraMetadata.BatteryTypeEnum]
        THIN: _ClassVar[ExtraMetadata.BatteryTypeEnum]
        VERTICAL: _ClassVar[ExtraMetadata.BatteryTypeEnum]
    THICK: ExtraMetadata.BatteryTypeEnum
    THIN: ExtraMetadata.BatteryTypeEnum
    VERTICAL: ExtraMetadata.BatteryTypeEnum
    class SensorDeviceEnum(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SENSOR_DEVICE_UNKNOWN: _ClassVar[ExtraMetadata.SensorDeviceEnum]
        SENSOR_DEVICE_FRONT: _ClassVar[ExtraMetadata.SensorDeviceEnum]
        SENSOR_DEVICE_REAR: _ClassVar[ExtraMetadata.SensorDeviceEnum]
        SENSOR_DEVICE_ALL: _ClassVar[ExtraMetadata.SensorDeviceEnum]
    SENSOR_DEVICE_UNKNOWN: ExtraMetadata.SensorDeviceEnum
    SENSOR_DEVICE_FRONT: ExtraMetadata.SensorDeviceEnum
    SENSOR_DEVICE_REAR: ExtraMetadata.SensorDeviceEnum
    SENSOR_DEVICE_ALL: ExtraMetadata.SensorDeviceEnum
    class ExtraUserOptions(_message.Message):
        __slots__ = ()
        def __init__(self) -> None: ...
    class Vector2(_message.Message):
        __slots__ = ("X", "Y")
        X_FIELD_NUMBER: _ClassVar[int]
        Y_FIELD_NUMBER: _ClassVar[int]
        X: int
        Y: int
        def __init__(self, X: _Optional[int] = ..., Y: _Optional[int] = ...) -> None: ...
    class GyroIndex(_message.Message):
        __slots__ = ()
        def __init__(self) -> None: ...
    class FileGroupInfoMsg(_message.Message):
        __slots__ = ("Type", "Index", "Identify")
        TYPE_FIELD_NUMBER: _ClassVar[int]
        INDEX_FIELD_NUMBER: _ClassVar[int]
        IDENTIFY_FIELD_NUMBER: _ClassVar[int]
        Type: int
        Index: int
        Identify: str
        def __init__(self, Type: _Optional[int] = ..., Index: _Optional[int] = ..., Identify: _Optional[str] = ...) -> None: ...
    class WindowCropInfoMsg(_message.Message):
        __slots__ = ("SrcWidth", "SrcHeight", "DstWidth", "DstHeight")
        SRCWIDTH_FIELD_NUMBER: _ClassVar[int]
        SRCHEIGHT_FIELD_NUMBER: _ClassVar[int]
        DSTWIDTH_FIELD_NUMBER: _ClassVar[int]
        DSTHEIGHT_FIELD_NUMBER: _ClassVar[int]
        SrcWidth: int
        SrcHeight: int
        DstWidth: int
        DstHeight: int
        def __init__(self, SrcWidth: _Optional[int] = ..., SrcHeight: _Optional[int] = ..., DstWidth: _Optional[int] = ..., DstHeight: _Optional[int] = ...) -> None: ...
    class GyroConfigInfo(_message.Message):
        __slots__ = ("AccRange", "GyroRange")
        ACCRANGE_FIELD_NUMBER: _ClassVar[int]
        GYRORANGE_FIELD_NUMBER: _ClassVar[int]
        AccRange: int
        GyroRange: int
        def __init__(self, AccRange: _Optional[int] = ..., GyroRange: _Optional[int] = ...) -> None: ...
    SERIALNUMBER_FIELD_NUMBER: _ClassVar[int]
    CAMERATYPE_FIELD_NUMBER: _ClassVar[int]
    FWVERSION_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    CREATIONTIME_FIELD_NUMBER: _ClassVar[int]
    FILESIZE_FIELD_NUMBER: _ClassVar[int]
    TOTALTIME_FIELD_NUMBER: _ClassVar[int]
    GPS_FIELD_NUMBER: _ClassVar[int]
    GYRO_FIELD_NUMBER: _ClassVar[int]
    ORIGINALOFFSET_FIELD_NUMBER: _ClassVar[int]
    TRIGGERSOURCE_FIELD_NUMBER: _ClassVar[int]
    DIMENSION_FIELD_NUMBER: _ClassVar[int]
    FRAMERATE_FIELD_NUMBER: _ClassVar[int]
    GAMMAMODE_FIELD_NUMBER: _ClassVar[int]
    FIRSTFRAMETIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    ROLLINGSHUTTERTIME_FIELD_NUMBER: _ClassVar[int]
    FILEGROUPINFO_FIELD_NUMBER: _ClassVar[int]
    WINDOWCROPINFO_FIELD_NUMBER: _ClassVar[int]
    GYROTIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    ISHASGYROTIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    TIMELAPSEINTERVAL_FIELD_NUMBER: _ClassVar[int]
    GYROCALIB_FIELD_NUMBER: _ClassVar[int]
    FIRSTGPSTIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    ISSELFIE_FIELD_NUMBER: _ClassVar[int]
    ISFLOWSTATEONLINE_FIELD_NUMBER: _ClassVar[int]
    ISDEWARP_FIELD_NUMBER: _ClassVar[int]
    RESOLUTIONSIZE_FIELD_NUMBER: _ClassVar[int]
    BATTERYTYPE_FIELD_NUMBER: _ClassVar[int]
    CAMPOSTURE_FIELD_NUMBER: _ClassVar[int]
    FOVTYPE_FIELD_NUMBER: _ClassVar[int]
    DISTANCE_FIELD_NUMBER: _ClassVar[int]
    FOV_FIELD_NUMBER: _ClassVar[int]
    GYROFILTERTYPE_FIELD_NUMBER: _ClassVar[int]
    GYROTYPE_FIELD_NUMBER: _ClassVar[int]
    OFFSETV2_FIELD_NUMBER: _ClassVar[int]
    OFFSETV3_FIELD_NUMBER: _ClassVar[int]
    ORIGINALOFFSETV2_FIELD_NUMBER: _ClassVar[int]
    ORIGINALOFFSETV3_FIELD_NUMBER: _ClassVar[int]
    FOCUSSENSOR_FIELD_NUMBER: _ClassVar[int]
    EXPECTOUTPUTTYPE_FIELD_NUMBER: _ClassVar[int]
    AUDIOMODE_FIELD_NUMBER: _ClassVar[int]
    ISRAWGYRO_FIELD_NUMBER: _ClassVar[int]
    RAWCAPTURETYPE_FIELD_NUMBER: _ClassVar[int]
    PTSTYPE_FIELD_NUMBER: _ClassVar[int]
    GYROCFGINFO_FIELD_NUMBER: _ClassVar[int]
    SerialNumber: str
    CameraType: str
    FwVersion: str
    Offset: str
    CreationTime: int
    FileSize: int
    TotalTime: int
    Gps: bytes
    Gyro: bytes
    OriginalOffset: str
    TriggerSource: ExtraMetadata.TriggerSourceEnum
    Dimension: ExtraMetadata.Vector2
    FrameRate: int
    GammaMode: str
    FirstFrameTimestamp: int
    RollingShutterTime: float
    FileGroupInfo: ExtraMetadata.FileGroupInfoMsg
    WindowCropInfo: ExtraMetadata.WindowCropInfoMsg
    GyroTimestamp: float
    IsHasGyroTimestamp: bool
    TimelapseInterval: int
    GyroCalib: bytes
    FirstGpsTimestamp: int
    IsSelfie: bool
    IsFlowstateOnline: bool
    IsDewarp: bool
    ResolutionSize: ExtraMetadata.Vector2
    BatteryType: ExtraMetadata.BatteryTypeEnum
    CamPosture: int
    FovType: int
    Distance: float
    Fov: float
    GyroFilterType: int
    GyroType: int
    OffsetV2: str
    OffsetV3: str
    OriginalOffsetV2: str
    OriginalOffsetV3: str
    FocusSensor: ExtraMetadata.SensorDeviceEnum
    ExpectOutputType: int
    AudioMode: int
    IsRawGyro: bool
    RawCaptureType: int
    PtsType: int
    GyroCfgInfo: ExtraMetadata.GyroConfigInfo
    def __init__(self, SerialNumber: _Optional[str] = ..., CameraType: _Optional[str] = ..., FwVersion: _Optional[str] = ..., Offset: _Optional[str] = ..., CreationTime: _Optional[int] = ..., FileSize: _Optional[int] = ..., TotalTime: _Optional[int] = ..., Gps: _Optional[bytes] = ..., Gyro: _Optional[bytes] = ..., OriginalOffset: _Optional[str] = ..., TriggerSource: _Optional[_Union[ExtraMetadata.TriggerSourceEnum, str]] = ..., Dimension: _Optional[_Union[ExtraMetadata.Vector2, _Mapping]] = ..., FrameRate: _Optional[int] = ..., GammaMode: _Optional[str] = ..., FirstFrameTimestamp: _Optional[int] = ..., RollingShutterTime: _Optional[float] = ..., FileGroupInfo: _Optional[_Union[ExtraMetadata.FileGroupInfoMsg, _Mapping]] = ..., WindowCropInfo: _Optional[_Union[ExtraMetadata.WindowCropInfoMsg, _Mapping]] = ..., GyroTimestamp: _Optional[float] = ..., IsHasGyroTimestamp: _Optional[bool] = ..., TimelapseInterval: _Optional[int] = ..., GyroCalib: _Optional[bytes] = ..., FirstGpsTimestamp: _Optional[int] = ..., IsSelfie: _Optional[bool] = ..., IsFlowstateOnline: _Optional[bool] = ..., IsDewarp: _Optional[bool] = ..., ResolutionSize: _Optional[_Union[ExtraMetadata.Vector2, _Mapping]] = ..., BatteryType: _Optional[_Union[ExtraMetadata.BatteryTypeEnum, str]] = ..., CamPosture: _Optional[int] = ..., FovType: _Optional[int] = ..., Distance: _Optional[float] = ..., Fov: _Optional[float] = ..., GyroFilterType: _Optional[int] = ..., GyroType: _Optional[int] = ..., OffsetV2: _Optional[str] = ..., OffsetV3: _Optional[str] = ..., OriginalOffsetV2: _Optional[str] = ..., OriginalOffsetV3: _Optional[str] = ..., FocusSensor: _Optional[_Union[ExtraMetadata.SensorDeviceEnum, str]] = ..., ExpectOutputType: _Optional[int] = ..., AudioMode: _Optional[int] = ..., IsRawGyro: _Optional[bool] = ..., RawCaptureType: _Optional[int] = ..., PtsType: _Optional[int] = ..., GyroCfgInfo: _Optional[_Union[ExtraMetadata.GyroConfigInfo, _Mapping]] = ...) -> None: ...
