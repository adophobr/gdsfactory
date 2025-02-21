from typing import Any, Dict, List, Optional, Tuple, Union, cast

import numpy as np
from numpy import cos, float64, int64, mod, ndarray, pi, sin
from phidl.device_layout import Device, DeviceReference

from gdsfactory.port import (
    Port,
    map_ports_layer_to_orientation,
    map_ports_to_orientation_ccw,
    map_ports_to_orientation_cw,
    select_ports,
)
from gdsfactory.snap import snap_to_grid

Number = Union[float64, int64, float, int]
Coordinate = Union[Tuple[Number, Number], ndarray, List[Number]]
Coordinates = Union[List[Coordinate], ndarray, List[Number], Tuple[Number, ...]]


class SizeInfo:
    def __init__(self, bbox: ndarray) -> None:
        self.west = bbox[0, 0]
        self.east = bbox[1, 0]
        self.south = bbox[0, 1]
        self.north = bbox[1, 1]

        self.width = self.east - self.west
        self.height = self.north - self.south

        xc = 0.5 * (self.east + self.west)
        yc = 0.5 * (self.north + self.south)

        self.sw = np.array([self.west, self.south])
        self.se = np.array([self.east, self.south])
        self.nw = np.array([self.west, self.north])
        self.ne = np.array([self.east, self.north])

        self.cw = np.array([self.west, yc])
        self.ce = np.array([self.east, yc])
        self.nc = np.array([xc, self.north])
        self.sc = np.array([xc, self.south])
        self.cc = self.center = np.array([xc, yc])

    def get_rect(
        self, padding=0, padding_w=None, padding_e=None, padding_n=None, padding_s=None
    ):
        w, e, s, n = self.west, self.east, self.south, self.north

        padding_n = padding if padding_n is None else padding_n
        padding_e = padding if padding_e is None else padding_e
        padding_w = padding if padding_w is None else padding_w
        padding_s = padding if padding_s is None else padding_s

        w = w - padding_w
        e = e + padding_e
        s = s - padding_s
        n = n + padding_n

        return [(w, s), (e, s), (e, n), (w, n)]

    @property
    def rect(self):
        return self.get_rect()

    def __str__(self):
        return "w: {}\ne: {}\ns: {}\nn: {}\n".format(
            self.west, self.east, self.south, self.north
        )


def _rotate_points(
    points: Coordinates,
    angle: int = 45,
    center: Coordinate = (
        0.0,
        0.0,
    ),
) -> ndarray:
    """Rotates points around a center point
    accepts single points [1,2] or array-like[N][2], and will return in kind

    Args:
        points: rotate points around center point
        angle:
        center:
    """
    # First check for common, easy values of angle
    p_arr = np.asarray(points)
    if angle == 0:
        return p_arr

    c0 = np.asarray(center)
    displacement = p_arr - c0
    if angle == 180:
        return c0 - displacement

    if p_arr.ndim == 2:
        perpendicular = displacement[:, ::-1]
    elif p_arr.ndim == 1:
        perpendicular = displacement[::-1]

    # Fall back to trigonometry
    angle = angle * pi / 180
    ca = cos(angle)
    sa = sin(angle)
    sa = np.array((-sa, sa))
    return displacement * ca + perpendicular * sa + c0


class ComponentReference(DeviceReference):
    def __init__(
        self,
        component: Device,
        origin: Coordinate = (0, 0),
        rotation: int = 0,
        magnification: None = None,
        x_reflection: bool = False,
        visual_label: str = "",
    ) -> None:
        super().__init__(
            device=component,
            origin=origin,
            rotation=rotation,
            magnification=magnification,
            x_reflection=x_reflection,
        )
        self.parent = component
        # The ports of a DeviceReference have their own unique id (uid),
        # since two DeviceReferences of the same parent Device can be
        # in different locations and thus do not represent the same port
        self._local_ports = {
            name: port._copy(new_uid=True) for name, port in component.ports.items()
        }
        self.visual_label = visual_label
        # self.uid = str(uuid.uuid4())[:8]

    def __repr__(self) -> str:
        return (
            'DeviceReference (parent Device "%s", ports %s, origin %s, rotation %s,'
            " x_reflection %s)"
            % (
                self.parent.name,
                list(self.ports.keys()),
                self.origin,
                self.rotation,
                self.x_reflection,
            )
        )

    def __str__(self) -> str:
        return self.__repr__()

    def to_dict(self):
        d = self.parent.to_dict()
        d.update(
            origin=self.origin,
            rotation=self.rotation,
            magnification=self.magnification,
            x_reflection=self.x_reflection,
        )
        return d

    @property
    def bbox(self):
        """Return the bounding box of the DeviceReference.
        it snaps to 3 decimals in um (0.001um = 1nm precission)
        """
        bbox = self.get_bounding_box()
        if bbox is None:
            bbox = ((0, 0), (0, 0))
        return np.round(bbox, 3)

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        """check with pydantic ComponentReference valid type"""
        assert isinstance(
            v, ComponentReference
        ), f"TypeError, Got {type(v)}, expecting ComponentReference"
        return v

    def __getitem__(self, val):
        """This allows you to access an alias from the reference's parent, and receive
        a copy of the reference which is correctly rotated and translated"""
        try:
            alias_device = self.parent[val]
        except Exception as exc:
            raise ValueError(
                '[PHIDL] Tried to access alias "%s" from parent '
                'Device "%s", which does not exist' % (val, self.parent.name)
            ) from exc
        new_reference = ComponentReference(
            alias_device.parent,
            origin=alias_device.origin,
            rotation=alias_device.rotation,
            magnification=alias_device.magnification,
            x_reflection=alias_device.x_reflection,
        )

        if self.x_reflection:
            new_reference.reflect((1, 0))
        if self.rotation is not None:
            new_reference.rotate(self.rotation)
        if self.origin is not None:
            new_reference.move(self.origin)

        return new_reference

    @property
    def ports(self) -> Dict[str, Port]:
        """This property allows you to access myref.ports, and receive a copy
        of the ports dict which is correctly rotated and translated"""
        for name, port in self.parent.ports.items():
            port = self.parent.ports[name]
            new_midpoint, new_orientation = self._transform_port(
                port.midpoint,
                port.orientation,
                self.origin,
                self.rotation,
                self.x_reflection,
            )
            if name not in self._local_ports:
                self._local_ports[name] = port.copy(new_uid=True)
            self._local_ports[name].midpoint = new_midpoint
            self._local_ports[name].orientation = mod(new_orientation, 360)
            self._local_ports[name].parent = self
        # Remove any ports that no longer exist in the reference's parent
        parent_names = self.parent.ports.keys()
        local_names = list(self._local_ports.keys())
        for name in local_names:
            if name not in parent_names:
                self._local_ports.pop(name)
        return self._local_ports

    @property
    def info(self) -> Dict[str, Any]:
        return self.parent.info

    @property
    def metadata_child(self) -> Dict[str, Any]:
        return self.parent.metadata_child

    @property
    def size_info(self) -> SizeInfo:
        return SizeInfo(self.bbox)

    def pprint_ports(self) -> None:
        """Pretty print component ports."""
        ports_list = self.get_ports_list()
        for port in ports_list:
            print(port)

    def _transform_port(
        self,
        point: ndarray,
        orientation: int,
        origin: Coordinate = (0, 0),
        rotation: Optional[int] = None,
        x_reflection: bool = False,
    ) -> Tuple[ndarray, int]:
        """Apply GDS-type transformation to a port (x_ref)"""
        new_point = np.array(point)
        new_orientation = orientation

        if x_reflection:
            new_point[1] = -new_point[1]
            new_orientation = -orientation
        if rotation is not None:
            new_point = _rotate_points(new_point, angle=rotation, center=[0, 0])
            new_orientation += rotation
        if origin is not None:
            new_point = new_point + np.array(origin)
        new_orientation = mod(new_orientation, 360)

        return new_point, int(new_orientation)

    def _transform_point(
        self,
        point: ndarray,
        origin: Coordinate = (0, 0),
        rotation: Optional[int] = None,
        x_reflection: bool = False,
    ) -> ndarray:
        """Apply GDS-type transformation to a point"""
        new_point = np.array(point)

        if x_reflection:
            new_point[1] = -new_point[1]
        if rotation is not None:
            new_point = _rotate_points(new_point, angle=rotation, center=[0, 0])
        if origin is not None:
            new_point = new_point + np.array(origin)

        return new_point

    def move(
        self,
        origin: Union[Port, Coordinate] = (0, 0),
        destination: Optional[Any] = None,
        axis: Optional[str] = None,
    ) -> "ComponentReference":
        """Move the DeviceReference from the origin point to the destination.
        Both origin and destination can be 1x2 array-like, Port, or a key
        corresponding to one of the Ports in this device_ref

        Returns:
            ComponentReference
        """

        # If only one set of coordinates is defined, make sure it's used to move things
        if destination is None:
            destination = origin
            origin = (0, 0)

        if hasattr(origin, "midpoint"):
            origin = cast(Port, origin)
            o = origin.midpoint
        elif np.array(origin).size == 2:
            o = origin
        elif origin in self.ports:
            origin = self.ports[origin]
            origin = cast(Port, origin)
            o = origin.midpoint
        else:
            raise ValueError(
                f"move(origin={origin})\n"
                f"Invalid origin = {origin!r} needs to be"
                f"a coordinate, port or port name {list(self.ports.keys())}"
            )

        if hasattr(destination, "midpoint"):
            destination = cast(Port, destination)
            d = destination.midpoint
        elif np.array(destination).size == 2:
            d = destination
        elif destination in self.ports:
            destination = self.ports[destination]
            destination = cast(Port, destination)
            d = destination.midpoint
        else:
            raise ValueError(
                f"{self.parent.name}.move(destination={destination}) \n"
                f"Invalid destination = {destination!r} needs to be"
                f"a coordinate, a port, or a valid port name {list(self.ports.keys())}"
            )

        # Lock one axis if necessary
        if axis == "x":
            d = (d[0], o[1])
        if axis == "y":
            d = (o[0], d[1])

        # This needs to be done in two steps otherwise floating point errors can accrue
        dxdy = np.array(d) - np.array(o)
        self.origin = np.array(self.origin) + dxdy
        self._bb_valid = False
        return self

    def rotate(
        self,
        angle: int = 45,
        center: Coordinate = (0.0, 0.0),
    ) -> "ComponentReference":
        """Return rotated ComponentReference

        Args:
            angle: in degrees
            center: x, y
        """
        if angle == 0:
            return self
        if isinstance(center, str) or isinstance(center, int):
            center = self.ports[center].position

        if isinstance(center, Port):
            center = center.midpoint
        self.rotation += angle
        self.rotation = self.rotation % 360
        self.origin = _rotate_points(self.origin, angle, center)
        self._bb_valid = False
        return self

    def reflect_h(
        self, port_name: Optional[str] = None, x0: Optional[Coordinate] = None
    ) -> None:
        """Perform horizontal mirror using x0 or port as axis (default, x0=0).
        This is the default for mirror along X=x0 axis
        """
        if port_name is None and x0 is None:
            x0 = -self.x

        if port_name is not None:
            position = self.ports[port_name]
            x0 = position.x
        self.reflect((x0, 1), (x0, 0))

    def reflect_v(
        self, port_name: Optional[str] = None, y0: Optional[float] = None
    ) -> None:
        """Perform vertical mirror using y0 as axis (default, y0=0)."""
        if port_name is None and y0 is None:
            y0 = 0.0

        if port_name is not None:
            position = self.ports[port_name]
            y0 = position.y
        self.reflect((1, y0), (0, y0))

    def reflect(
        self,
        p1: Coordinate = (0.0, 1.0),
        p2: Coordinate = (0.0, 0.0),
    ) -> "ComponentReference":
        if isinstance(p1, Port):
            p1 = p1.midpoint
        if isinstance(p2, Port):
            p2 = p2.midpoint
        p1 = np.array(p1)
        p2 = np.array(p2)
        # Translate so reflection axis passes through origin
        self.origin = self.origin - p1

        # Rotate so reflection axis aligns with x-axis
        angle = np.arctan2((p2[1] - p1[1]), (p2[0] - p1[0])) * 180 / pi
        self.origin = _rotate_points(self.origin, angle=-angle, center=(0, 0))
        self.rotation -= angle

        # Reflect across x-axis
        self.x_reflection = not self.x_reflection
        self.origin[1] = -1 * self.origin[1]
        self.rotation = -1 * self.rotation

        # Un-rotate and un-translate
        self.origin = _rotate_points(self.origin, angle=angle, center=(0, 0))
        self.rotation += angle
        self.rotation = self.rotation % 360
        self.origin = self.origin + p1

        self._bb_valid = False
        return self

    def connect(
        self, port: Union[str, Port], destination: Port, overlap: float = 0.0
    ) -> "ComponentReference":
        """Return Component reference where a port or port_name connects to a destination

        Args:
            port: origin (port or port_name) to connect.
            destination: destination port.
            overlap: how deep does the port go inside.

        Returns:
            ComponentReference
        """
        # ``port`` can either be a string with the name or an actual Port
        if port in self.ports:  # Then ``port`` is a key for the ports dict
            p = self.ports[port]
        elif isinstance(port, Port):
            p = port
        else:
            ports = list(self.ports.keys())
            raise ValueError(
                f"port = {port!r} not in {self.parent.name!r} ports {ports}"
            )

        angle = 180 + destination.orientation - p.orientation
        angle = angle % 360
        self.rotate(angle=angle, center=p.midpoint)

        self.move(origin=p, destination=destination)
        self.move(
            -overlap
            * np.array(
                [
                    cos(destination.orientation * pi / 180),
                    sin(destination.orientation * pi / 180),
                ]
            )
        )
        return self

    def get_ports_list(self, **kwargs) -> List[Port]:
        """Return a list of ports.

        Keyword Args:
            layer: port GDS layer
            prefix: port name prefix
            orientation: in degrees
            width: port width
            layers_excluded: List of layers to exclude
            port_type: optical, electrical, ...
            clockwise: if True, sort ports clockwise, False: counter-clockwise
        """
        return list(select_ports(self.ports, **kwargs).values())

    def get_ports_dict(self, **kwargs) -> Dict[str, Port]:
        """Return a dict of ports.

        Keyword Args:
            layer: port GDS layer
            prefix: port name prefix
            orientation: in degrees
            width: port width
            layers_excluded: List of layers to exclude
            port_type: optical, electrical, ...
            clockwise: if True, sort ports clockwise, False: counter-clockwise
        """
        return select_ports(self.ports, **kwargs)

    @property
    def ports_layer(self) -> Dict[str, str]:
        """Return a mapping from layer0_layer1_E0: portName"""
        return map_ports_layer_to_orientation(self.ports)

    def port_by_orientation_cw(self, key: str, **kwargs):
        """Return port by indexing them clockwise"""
        m = map_ports_to_orientation_cw(self.ports, **kwargs)
        if key not in m:
            raise KeyError(f"{key} not in {list(m.keys())}")
        key2 = m[key]
        return self.ports[key2]

    def port_by_orientation_ccw(self, key: str, **kwargs):
        """Return port by indexing them clockwise"""
        m = map_ports_to_orientation_ccw(self.ports, **kwargs)
        if key not in m:
            raise KeyError(f"{key} not in {list(m.keys())}")
        key2 = m[key]
        return self.ports[key2]

    def snap_ports_to_grid(self, nm: int = 1) -> None:
        for port in self.ports.values():
            port.snap_to_grid(nm=nm)

    def get_ports_xsize(self, **kwargs) -> float:
        """Return xdistance from east to west ports

        Keyword Args:
            kwargs: orientation, port_type, layer
        """
        ports_cw = self.get_ports_list(clockwise=True, **kwargs)
        ports_ccw = self.get_ports_list(clockwise=False, **kwargs)
        return snap_to_grid(ports_ccw[0].x - ports_cw[0].x)

    def get_ports_ysize(self, **kwargs) -> float:
        """Returns ydistance from east to west ports"""
        ports_cw = self.get_ports_list(clockwise=True, **kwargs)
        ports_ccw = self.get_ports_list(clockwise=False, **kwargs)
        return snap_to_grid(ports_ccw[0].y - ports_cw[0].y)
