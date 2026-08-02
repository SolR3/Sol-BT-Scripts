from dataclasses import dataclass


def format_time(total_time):
    m = total_time/60
    minutes = int(m)
    seconds = round((m - minutes)*60)

    runtime_text = [f"{minutes} minutes"] if minutes else []
    if seconds:
        runtime_text += [f"{seconds} seconds"]
    runtime_text = ", ".join(runtime_text)

    return runtime_text


@dataclass
class FinneyBlockData:
    block: int | None
    time: int
