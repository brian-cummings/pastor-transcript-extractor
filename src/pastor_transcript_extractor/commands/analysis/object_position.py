"""Object-position check CLI: one whole-sermon, object-centered request and its judged acceptance (docs/OBJECT_POSITION_CHECK.md)."""
from pathlib import Path
import json

import typer
from httpx import HTTPError

from ..apps import analysis_app

app = typer.Typer(help='Run the object-position check: one object-centered request over a whole sermon, judged against frozen components.')
analysis_app.add_typer(app, name='object-position')
ERRORS = (ValueError, OSError, KeyError, TypeError, StopIteration, HTTPError, RuntimeError)
CHECK_NAME = 'object-position-check-v1'


def _paths(base_dir: Path) -> tuple[Path, Path]:
    from ...bound_claims.common import ensure_outside_repository, pilot_dir
    from ...config import build_paths, evaluation_root_for
    return (pilot_dir(base_dir) / 'leaf' / 'leaf_observations.json',
            ensure_outside_repository(evaluation_root_for(build_paths(base_dir), base_dir) / CHECK_NAME))


@app.command('check')
def check(base_dir: Path = typer.Option(..., '--base-dir', help='Application base directory.'),
          object_name: str = typer.Option(..., '--object', help='The object whose position is asked for, e.g. "the American experiment".'),
          video: int = typer.Option(..., '--video', help='Video id of the sermon in the pilot leaf table.'),
          check_only: bool = typer.Option(False, '--check-only', help='Report size, reservation and component locations; sends nothing and writes nothing.')):
    """Send the one reserved whole-sermon request (or check it); no semantic retry and no second run."""
    from ...object_position import runner
    try:
        leaf, output = _paths(base_dir)
        typer.echo(json.dumps(runner.run(leaf, output, video, object_name, check_only=check_only), indent=2, ensure_ascii=False))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error


@app.command('review')
def review(base_dir: Path = typer.Option(..., '--base-dir', help='Application base directory.'),
           packet_only: bool = typer.Option(False, '--packet-only', help='Write REVIEW.md and stop before the judging loop.')):
    """Write the review packet, collect your judgments (resumable), then write REPORT.md and REPORT.json."""
    from ...bound_claims.common import read_json
    from ...object_position import review as reviewing, sermon as sermons
    try:
        leaf, output = _paths(base_dir)
        result = read_json(output / 'result.json')
        text = reviewing.packet(result, sermons.load(leaf, result['video_id']))
        (output / 'REVIEW.md').write_text(text + '\n')
        typer.echo(f'Review packet: {output / "REVIEW.md"}')
        if not packet_only:
            reviewing.judge(output, input, typer.echo)
            typer.echo(json.dumps(reviewing.report(output), indent=2, ensure_ascii=False))
    except ERRORS as error:
        raise typer.BadParameter(str(error)) from error
