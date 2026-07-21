"""Automatic physical room assignment.

Matches a reservation (or one of its room lines, for multi-room
bookings) to a free `Room` by exact `category` == `room_type` string
match and no date overlap with any other currently-assigned
reservation/room-line covering the same room. Assignment is
best-effort: if no room of the right category is free, the line is
simply left unassigned (still prints/works fine) and can be assigned
manually later, e.g. once a category is added or a conflicting stay
is moved.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation, ReservationStatus
from app.models.reservation_room_line import ReservationRoomLine
from app.models.room import Room


async def _occupied_room_ids(
    db: AsyncSession, *, checkin: date, checkout: date, exclude_reservation_id: int | None = None
) -> set[int]:
    reservation_query = select(Reservation.assigned_room_id).where(
        Reservation.assigned_room_id.is_not(None),
        Reservation.status != ReservationStatus.cancelled,
        Reservation.checkin < checkout,
        Reservation.checkout > checkin,
    )
    room_line_query = (
        select(ReservationRoomLine.assigned_room_id)
        .join(Reservation, Reservation.id == ReservationRoomLine.reservation_id)
        .where(
            ReservationRoomLine.assigned_room_id.is_not(None),
            Reservation.status != ReservationStatus.cancelled,
            Reservation.checkin < checkout,
            Reservation.checkout > checkin,
        )
    )
    if exclude_reservation_id is not None:
        reservation_query = reservation_query.where(Reservation.id != exclude_reservation_id)
        room_line_query = room_line_query.where(Reservation.id != exclude_reservation_id)

    reservation_ids = set((await db.execute(reservation_query)).scalars().all())
    room_line_ids = set((await db.execute(room_line_query)).scalars().all())
    return (reservation_ids | room_line_ids) - {None}


async def find_free_room(
    db: AsyncSession,
    *,
    category: str,
    checkin: date,
    checkout: date,
    exclude_reservation_id: int | None = None,
    exclude_room_ids: set[int] | None = None,
) -> Room | None:
    occupied = await _occupied_room_ids(
        db, checkin=checkin, checkout=checkout, exclude_reservation_id=exclude_reservation_id
    )
    if exclude_room_ids:
        occupied |= exclude_room_ids

    query = select(Room).where(Room.category == category, Room.is_active.is_(True)).order_by(Room.room_number)
    if occupied:
        query = query.where(Room.id.notin_(occupied))

    return (await db.execute(query)).scalars().first()


async def assign_rooms_for_reservation(db: AsyncSession, reservation: Reservation) -> None:
    """Assign a free room to each unassigned room line, or (for the
    legacy single-room_type path used by reservations with no room
    lines) to the reservation itself. Mutates in place; caller flushes
    /commits.

    Callers typically invoke this right after `db.flush()`ing a brand
    new reservation whose `room_lines` collection was never touched
    in-memory (e.g. the parser produced none) — on a persistent object
    that triggers a real lazy SQL load outside of a greenlet context
    and crashes, so it's refreshed explicitly here first."""
    await db.refresh(reservation, attribute_names=["room_lines"])
    if reservation.room_lines:
        assigned_this_call: set[int] = set()
        for line in reservation.room_lines:
            if line.assigned_room_id is not None:
                assigned_this_call.add(line.assigned_room_id)
                continue
            room = await find_free_room(
                db,
                category=line.room_type,
                checkin=reservation.checkin,
                checkout=reservation.checkout,
                exclude_reservation_id=reservation.id,
                exclude_room_ids=assigned_this_call,
            )
            if room is not None:
                line.assigned_room_id = room.id
                assigned_this_call.add(room.id)
    elif reservation.room_type and reservation.assigned_room_id is None:
        room = await find_free_room(
            db,
            category=reservation.room_type,
            checkin=reservation.checkin,
            checkout=reservation.checkout,
            exclude_reservation_id=reservation.id,
        )
        if room is not None:
            reservation.assigned_room_id = room.id


async def rooms_occupied_on_date(db: AsyncSession, target_date: date) -> dict[int, str]:
    """Room id -> guest name occupying it on target_date, for display
    purposes (e.g. the arrivals sheet's room-assignment dropdown) —
    not the authoritative overlap check assignment itself uses."""
    reservation_query = select(Reservation.assigned_room_id, Reservation.guest_name).where(
        Reservation.assigned_room_id.is_not(None),
        Reservation.status != ReservationStatus.cancelled,
        Reservation.checkin <= target_date,
        Reservation.checkout > target_date,
    )
    room_line_query = (
        select(ReservationRoomLine.assigned_room_id, Reservation.guest_name)
        .join(Reservation, Reservation.id == ReservationRoomLine.reservation_id)
        .where(
            ReservationRoomLine.assigned_room_id.is_not(None),
            Reservation.status != ReservationStatus.cancelled,
            Reservation.checkin <= target_date,
            Reservation.checkout > target_date,
        )
    )
    occupied: dict[int, str] = {}
    for room_id, guest_name in (await db.execute(reservation_query)).all():
        occupied[room_id] = guest_name
    for room_id, guest_name in (await db.execute(room_line_query)).all():
        occupied[room_id] = guest_name
    return occupied


async def room_plan_grid(
    db: AsyncSession, start_date: date, end_date: date
) -> dict[int, dict[date, tuple[int, str]]]:
    """room_id -> {date: (reservation_id, guest_name)} for every day in
    [start_date, end_date) the room is occupied — powers the "Plahta"
    room-by-date grid view. Fetches each assignment path (the
    reservation-level and the per-room-line assigned_room_id) once for
    the whole range and expands into individual days in Python, rather
    than one query per day."""
    reservation_query = select(
        Reservation.id, Reservation.assigned_room_id, Reservation.guest_name, Reservation.checkin, Reservation.checkout
    ).where(
        Reservation.assigned_room_id.is_not(None),
        Reservation.status != ReservationStatus.cancelled,
        Reservation.checkin < end_date,
        Reservation.checkout > start_date,
    )
    room_line_query = (
        select(
            Reservation.id,
            ReservationRoomLine.assigned_room_id,
            Reservation.guest_name,
            Reservation.checkin,
            Reservation.checkout,
        )
        .join(Reservation, Reservation.id == ReservationRoomLine.reservation_id)
        .where(
            ReservationRoomLine.assigned_room_id.is_not(None),
            Reservation.status != ReservationStatus.cancelled,
            Reservation.checkin < end_date,
            Reservation.checkout > start_date,
        )
    )

    grid: dict[int, dict[date, tuple[int, str]]] = {}
    rows = list((await db.execute(reservation_query)).all()) + list((await db.execute(room_line_query)).all())
    for reservation_id, room_id, guest_name, checkin, checkout in rows:
        day = max(checkin, start_date)
        last_day = min(checkout, end_date)
        while day < last_day:
            grid.setdefault(room_id, {})[day] = (reservation_id, guest_name)
            day += timedelta(days=1)

    return grid


async def reassign_rooms_for_reservation(db: AsyncSession, reservation: Reservation) -> None:
    """Clear any existing assignment and re-run auto-assignment — used
    by the manual "Reassign" action, e.g. after adding new rooms or
    freeing up a conflicting stay."""
    reservation.assigned_room_id = None
    for line in reservation.room_lines:
        line.assigned_room_id = None
    await assign_rooms_for_reservation(db, reservation)
