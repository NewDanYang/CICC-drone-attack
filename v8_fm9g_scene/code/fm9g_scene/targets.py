"""Non-balloon target classes recognised by FM9G4B-V.

Scene inventory comes from the track rules (打击.pdf §2.1): two square pillars
(>=0.5x0.5x1.5 m), one square crossing frame (opening >=0.9 m, outer 1.3 m per
llm_mission.launch), one ground ArUco marker (>=0.15 m), one circular
take-off/landing marker (diameter <=0.8 m).  Balloons are handled by the
balloon bridge and are deliberately absent here.

Prompt design:
* `ground` asks for FM9G's native `<box>` (0..1000).  The 5.0 study showed this
  is unreliable for 20-40 px balloons; these targets are 100-300 px and
  high-contrast, which is exactly what offline_eval.py must confirm on real
  frames before flight.
* `verify` is a contrastive yes/no question asked on the crop of the proposed
  box; P(是) becomes the published score.  It names the confusers seen in the
  real failure (brick blocks next to the frame) so they score low.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetSpec:
    name: str
    camera: str             # 'front' (sensor1 + depth) or 'down' (sensor2 + ground plane)
    ground: str             # native-box grounding prompt
    verify: str             # contrastive yes/no prompt for the box crop
    multi: bool = False     # more than one instance expected
    depth_mode: str = 'solid'
    width_m: float = 0.0    # physical size used for size<->depth consistency
    height_m: float = 0.0
    size_range_m: tuple = (0.0, 99.0)   # plausible metric size (ground targets)
    verify_threshold: float = 0.7
    # window search (method 'scan'): FM9G answers scan_prompt for every window
    scan_prompt: str = ''
    scan_sides: tuple = (96, 128, 160, 200, 240, 280)   # window heights, px
    scan_aspect: float = 1.0                             # window width / height
    scan_threshold: float = 0.5                          # min FM9G P(是) for a seed

    def ground_prompt(self):
        many = '每个目标各输出一个' if self.multi else '只输出一个'
        return ('请找出图中的' + self.ground + '。' + many +
                '<box>x1 y1 x2 y2</box>，坐标归一化到0到1000，x向右、y向下；'
                '图中没有时输出<box>None</box>。不要解释。')


TARGETS = {
    'square_frame': TargetSpec(
        name='square_frame', camera='front',
        ground='方形穿越框（四条边围成、中间镂空、无人机可以从中间穿过的方框，只框住方框本身）',
        verify='这张图片的主体是不是一个中间镂空、可以让无人机穿过的方形框？'
               '砖块、砖墙、实心柱子都不算。只回答“是”或“否”。',
        depth_mode='hollow', width_m=1.3, height_m=1.3,
        # 1.3 m frame at 1.5-6 m depth with fx=320 -> ~70-280 px
        scan_prompt='这张图片是否正好框住一个完整的方形穿越框：方框的四条边都完整可见并且靠近图片边缘，'
                    '中间是镂空的？砖块、墙、柱子不算。只回答“是”或“否”。',
        scan_sides=(72, 104, 150, 215, 300)),
    'pillar': TargetSpec(
        name='pillar', camera='front', multi=True,
        ground='方形障碍柱（立在地面上的实心方柱）',
        verify='这张图片的主体是不是一根立在地面上的实心方形柱子？'
               '镂空的方框、墙面都不算。只回答“是”或“否”。',
        depth_mode='solid', width_m=0.5, height_m=1.5,
        scan_prompt='这张图片是否正好框住一根完整的立在地面上的实心方形柱子，柱子占满图片大部分？'
                    '镂空的方框、墙面不算。只回答“是”或“否”。',
        scan_sides=(200, 300, 420), scan_aspect=0.45),
    'aruco_marker': TargetSpec(
        name='aruco_marker', camera='down',
        ground='地面上的黑白方形二维码标识',
        verify='这张图片里有没有一个黑白相间的方形二维码标识？只回答“是”或“否”。',
        size_range_m=(0.1, 1.2),
        scan_prompt='这张图片是否正好框住一个完整的黑白方形二维码标识，二维码占满图片大部分？只回答“是”或“否”。',
        scan_sides=(100, 150, 220, 300)),
    'landing_pad': TargetSpec(
        name='landing_pad', camera='down',
        ground='地面上的圆形无人机起降标识',
        verify='这张图片里有没有一个画在地面上的圆形无人机起降标识？'
               '二维码不算。只回答“是”或“否”。',
        size_range_m=(0.3, 1.2),
        scan_prompt='这张图片是否正好框住一个完整的画在地面上的圆形无人机起降标识，标识占满图片大部分？'
                    '二维码不算。只回答“是”或“否”。',
        scan_sides=(110, 170, 250, 350)),
}
