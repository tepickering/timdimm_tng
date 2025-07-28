import os
import json
import pkg_resources

from collections import UserDict

import xmltodict

from pathlib import Path

from astropy.table import Table
import astropy.units as u


class ScheduleBase(UserDict):
    """
    Base class for INDI/Ekos scheduler configurations with utilities to read/write
    them to XML/JSON
    """

    def from_json(
        self,
        filename=pkg_resources.resource_filename(
            __name__, os.path.join("templates", "timdimm_sequence_template.json")
        ),
    ):
        """
        Instantiate from a JSON file
        """
        with open(filename, "r") as fp:
            self.data = json.load(fp)

    def from_xml(self, filename="sequence.esq"):
        """
        Instantiate from an XML file
        """
        with open(filename, "r") as fp:
            self.data = xmltodict.parse(fp.read())

    def to_xml(self, filename="sequence.esq"):
        """
        Convert internal dict to XML and write to file
        """
        with open(filename, "w") as fp:
            fp.write(xmltodict.unparse(self.data, pretty=True, indent="    " ))

    def to_json(self, filename="sequence.json"):
        """
        Convert internal dict to JSON and write to file
        """
        with open(filename, "w") as fp:
            json.dump(self.data, fp, indent=4)


class Sequence(ScheduleBase):
    """
    Handle observing sequence configurations
    """

    def __init__(
        self,
        template=pkg_resources.resource_filename(
            __name__, os.path.join("templates", "timdimm_sequence.esq")
        ),
    ):
        if "json" in Path(template).suffix.lower():
            self.from_json(filename=template)
        else:
            self.from_xml(filename=template)


class Observation(ScheduleBase):
    """
    Job entry in an INDI/Ekos Scheduler list
    """

    def __init__(
        self,
        target="Target",
        ra=0.0,
        dec=0.0,
        priority=10,
        sequence=pkg_resources.resource_filename(
            __name__, os.path.join("templates", "timdimm_sequence.esq")
        ),
        template=pkg_resources.resource_filename(
            __name__, os.path.join("templates", "timdimm_schedule_template.esl")
        ),
    ):
        if "json" in Path(template).suffix.lower():
            self.from_json(filename=template)
        else:
            self.from_xml(filename=template)

        # use the first entry in the scheduler list template as the boiler-plate to build from
        self.data = self.data["SchedulerList"]["Job"][0]

        # configure from the arguments
        self.data["Name"] = target
        self.data["Priority"] = (
            f"{priority}"  # XML can only be strings so we make sure they are
        )
        self.data["Coordinates"]["J2000RA"] = f"{ra}"
        self.data["Coordinates"]["J2000DE"] = f"{dec}"
        self.data["Sequence"] = str(sequence)


class Schedule(ScheduleBase):
    """
    Wrap an INDI/Ekos Scheduler list and provide ways to build them programmatically
    and write them to valid JSON/XML
    """

    def __init__(
        self,
        template=pkg_resources.resource_filename(
            __name__, os.path.join("templates", "timdimm_schedule_template.esl")
        ),
    ):
        if "json" in Path(template).suffix.lower():
            self.from_json(filename=template)
        else:
            self.from_xml(filename=template)

        # zero out the list of jobs to initiate
        self.data["SchedulerList"]["Job"] = []

    def add_observation(self, observation):
        """
        Add an Observation instance to the schedule
        """
        self.data["SchedulerList"]["Job"].append(observation)


def mag_to_priority(mag):
    """
    Use a star's magnitude as a basis for calculating priority. Brighter stars have
    higher priority since they can be observed thru more cloud cover. Range covered is from
    -1.5 to 3.5. Sirius is brightest at -1.46, 3.5 is the faintest that can be observed usefully
    with 1 ms exposures.
    """
    priority = int(4 * (mag + 1.5)) + 1
    if priority > 20:
        priority = 20
    return priority


def make_timdimm_schedule(outfile="timdimm_schedule.esl"):
    sched = Schedule()
    stars = Table.read(pkg_resources.resource_filename(__name__, "star_list.ecsv"))

    # looks like Ekos only used the order of the schedule and doesn't factor in priority.
    # so we sort by brightness so it'll always stick with the brightest star available.
    stars.sort(keys="Vmag")
    for star in stars:
        # Don't have to go much below 2nd mag to get enough stars
        if star["Vmag"] < 2.1:
            priority = mag_to_priority(star["Vmag"])
            obs = Observation(
                target=star["Name"],
                ra=star["Coordinates"].ra.to(u.hourangle).value,
                dec=star["Coordinates"].dec.value,
                priority=priority,
            )
            sched.add_observation(dict(obs))

    if outfile is not None:
        sched.to_xml(outfile)

    return sched


def make_hdimm_schedule(outfile="hdimm_schedule.esl"):
    sched = Schedule(
        template=pkg_resources.resource_filename(
            __name__, os.path.join("templates", "hdimm_schedule_template.esl")
        )
    )
    stars = Table.read(pkg_resources.resource_filename(__name__, "star_list_full.ecsv"))

    # looks like Ekos only used the order of the schedule and doesn't factor in priority.
    # so we sort by brightness so it'll always stick with the brightest star available.
    stars.sort(keys="Vmag")
    for star in stars:
        if star["Coordinates"].dec.value > -10 and star["Vmag"] < 2.0:
            priority = mag_to_priority(star["Vmag"])
            obs = Observation(
                target=star["Name"],
                ra=star["Coordinates"].ra.to(u.hourangle).value,
                dec=star["Coordinates"].dec.value,
                priority=priority,
                sequence=pkg_resources.resource_filename(
                    __name__, os.path.join("templates", "hdimm_sequence.esq")
                ),
                template=pkg_resources.resource_filename(
                    __name__, os.path.join("templates", "hdimm_schedule_template.esl")
                ),
            )
            sched.add_observation(dict(obs))

    if outfile is not None:
        sched.to_xml(outfile)

    return sched
