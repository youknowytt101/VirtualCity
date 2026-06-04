# Cave ArtStation Quality Optimization Plan

## Goal

Target look: realistic AAA cave environment, mysterious, humid, massive, with a restrained explorer camp story. The shot should feel like a polished ArtStation Unreal Engine environment render rather than a raw editor viewport screenshot.

## Current Project Rendering Baseline

The current UE project config at `UE5/VirtualCityUE/Config/DefaultEngine.ini` is not set up for high-end cinematic cave rendering yet:

- `r.DynamicGlobalIlluminationMethod=0`: Lumen GI is disabled.
- `r.ReflectionMethod=0`: Lumen reflections are disabled.
- `r.Shadow.Virtual.Enable=0`: Virtual Shadow Maps are disabled.
- `DefaultGraphicsRHI=DefaultGraphicsRHI_DX11`: project defaults to DX11.
- `r.DefaultFeature.AutoExposure=False`: auto exposure is disabled, which is good for manual shot control, but the scene still needs a Post Process Volume with deliberate exposure and local exposure settings.

For a portfolio-quality cave shot, create a duplicate showcase map or lighting variant first. Do not globally switch the whole production project unless performance and compatibility have been reviewed.

Recommended high-quality screenshot profile:

```ini
[/Script/Engine.RendererSettings]
r.DefaultFeature.AutoExposure=False
r.DynamicGlobalIlluminationMethod=1
r.ReflectionMethod=1
r.Shadow.Virtual.Enable=1
r.Nanite.ProjectEnabled=True

[/Script/WindowsTargetPlatform.WindowsTargetSettings]
DefaultGraphicsRHI=DefaultGraphicsRHI_DX12
+D3D12TargetedShaderFormats=PCD3D_SM6
```

Use Project Settings if possible:

- Rendering > Global Illumination: Lumen
- Rendering > Reflections: Lumen
- Rendering > Shadow Map Method: Virtual Shadow Maps
- Platforms > Windows > Default RHI: DirectX 12
- Enable Nanite on rock meshes where appropriate

## The 10 Biggest Visual Problems

### 1. Central Rock Is Overexposed

Symptoms:

- The central slope reads as a white mass.
- Rock texture, cracks, and material variation are lost.
- The eye is forced into the blown-out area instead of following the whole cave composition.

UE actions:

- Add or tune an unbound Post Process Volume.
- Use manual exposure.
- Start with Exposure Compensation around `-0.7` to `-1.3`.
- Enable Local Exposure and reduce highlight dominance.
- Lower the central rock material BaseColor brightness if it is physically too bright.
- Check the Buffer Visualization > Base Color view. The rock should not be close to pure white.

Target:

- Sunlight still feels strong.
- Rock detail remains visible in the lit zone.
- No large area clips to flat white.

### 2. Dark Side Walls Are Too Crushed

Symptoms:

- Left and right cave walls feel like black silhouettes.
- Cave scale is strong, but material work is hidden.

UE actions:

- Use Lumen GI and a low-intensity cool Sky Light.
- Add one or two large, very soft Rect Lights as invisible bounce cards if needed.
- Keep fill light subtle. The cave should stay moody, not evenly lit.

Starting values:

- Sky Light: Movable, intensity `0.15` to `0.6`, cool tint.
- Rect Light fill: large source width, low intensity, cool gray-blue.
- Avoid direct fill on the campfire area.

Target:

- Side walls remain dark, but rock planes and silhouettes are readable.

### 3. Visual Path Is Not Deliberate Enough

Current desired path:

Foreground camp warmth -> central sunlit rock -> right waterfalls -> upper cave opening.

UE actions:

- Make foreground camp light the first warm accent.
- Keep central sunlight as the dominant shape, but not clipped.
- Add mist and foam around the waterfalls so they become a readable secondary focal point.
- Slightly darken non-focal side zones using lighting, fog, or subtle post-process vignette.

Target:

- Viewer understands the shot in three reads: camp, cave scale, waterfall.

### 4. Rock Material Reads Too Uniform

Symptoms:

- Large rocks have similar color and roughness.
- Material looks like repeated scans rather than art-directed geology.

UE actions:

- Build or extend a master rock material with 4 blend layers:
  - dry limestone
  - wet dark rock
  - moss / organic growth
  - pale mineral deposits
- Drive blending through Vertex Color plus decals.
- Add macro color variation using world position noise.
- Add cavity darkening and edge breakup.

Material targets:

- BaseColor: gray limestone, brown-black damp stone, muted moss green, pale mineral streaks.
- Roughness: dry `0.65` to `0.9`, wet `0.18` to `0.42`.
- Specular: keep restrained, around `0.35` to `0.55`.
- Normal: combine scan normal with detail normal for close-up breakup.
- AO: stronger in cracks and contact zones, not uniformly dark.

### 5. Wetness Is Not Localized Enough

Symptoms:

- Waterfalls exist, but nearby rock does not respond enough.
- Cave does not feel humid.

UE actions:

- Add wetness masks around waterfalls, waterline, drainage paths, and the ground near puddles.
- Use decals for vertical water streaks.
- Darken wet BaseColor and lower Roughness.
- Add small reflective highlights on protruding rocks near water.

Wetness material function:

```text
WetMask
  -> BaseColor = lerp(BaseColor, BaseColor * 0.55, WetMask)
  -> Roughness = lerp(Roughness, 0.24, WetMask)
  -> Specular = lerp(Specular, 0.52, WetMask)
  -> Add subtle detail normal intensity in wet streaks
```

### 6. Waterfalls Need VFX Layers

Symptoms:

- Waterfall reads as white vertical strips.
- There is not enough spray, foam, splash, or humidity.

UE actions:

- Waterfall mesh/material:
  - Use panning normal maps.
  - Use Flow Map or directional UV distortion.
  - Use noise to break alpha edges.
  - Use Depth Fade at rock intersections.
- Niagara layers:
  - Mist emitter along the falling water.
  - Splash emitter at impact points.
  - Foam cards or decals on the water surface.
  - Fine drifting mist near the cave floor.

Niagara starting setup:

- Mist:
  - translucent soft sprite
  - low opacity
  - slow upward / outward velocity
  - random size variation
- Splash:
  - short lifetime
  - gravity affected
  - brighter near impact
- Foam:
  - decal or flat mesh cards
  - panning breakup texture
  - fade by distance and depth

### 7. Atmosphere Is Too Empty

Symptoms:

- Large cave volume does not have enough air depth.
- Light shafts are not visually carrying the space.

UE actions:

- Use Exponential Height Fog with Volumetric Fog enabled.
- Keep global fog subtle.
- Add local fog/mist cards or Niagara only near waterfalls, cave opening, and wet ground.
- Use the cave opening Directional Light to create readable shafts.

Starting values:

- Exponential Height Fog density: low, start around `0.01` to `0.03`.
- Volumetric Scattering Intensity: tune around `0.3` to `0.8`.
- Directional Light Volumetric Scattering: start around `1.0`, adjust down if it washes the image.

Target:

- Background layers separate clearly.
- Light beams are visible but not theatrical fantasy beams.

### 8. Foreground Story Is Too Weak

Symptoms:

- Warm light is promising, but the camp story is not legible enough.
- The scene lacks a clear human-scale narrative hook.

UE actions:

- Add a restrained abandoned exploration camp cluster.
- Keep props grouped around the existing warm light and wooden planks.
- Avoid random clutter across the whole floor.

Recommended props:

- oil lantern or low campfire
- charred stones
- broken crate
- rope coil
- old mining tool
- wet footprints or drag marks
- broken railing section
- small cloth or tarp remnant

Target:

- One compact story cluster, not scattered noise.

### 9. Scale Reference Needs More Support

Symptoms:

- Cave is large, but scale could be more convincing.

UE actions:

- Add small structural references:
  - distant railing near waterfall
  - old ladder on a rock shelf
  - rope hanging from a high ledge
  - tiny wooden support beams near a dark tunnel
- Use these sparingly.

Target:

- Viewer immediately feels how huge the cave is.

### 10. Screenshot Polish Is Still Viewport-Like

Symptoms:

- Editor UI is visible in the screenshot.
- Image needs a dedicated camera and Movie Render Queue pass.

UE actions:

- Create a Cine Camera Actor.
- Use a clean cinematic camera, not the editor viewport.
- Render via Movie Render Queue.
- Capture breakdown views for portfolio:
  - Final Lit
  - Detail Lighting
  - Unlit/BaseColor
  - Lighting Only
  - Material/Decal closeups
  - Niagara breakdown

Camera starting point:

- Focal length: `28mm` to `35mm`.
- Camera height: slightly lower than current if you want more cave scale.
- Keep wide panoramic composition if that is the desired hero shot.
- Avoid heavy DOF; the environment should stay readable.

## Lighting Setup Recipe

### Directional Light

Purpose: sunlight through cave opening.

Actions:

- Position angle so the strongest shaft lands on the central slope but also grazes rock edges.
- Do not solve brightness by simply increasing light intensity.
- Use exposure, material values, and local exposure to control highlight clipping.

Starting range:

- Intensity: art-directed, test within `5` to `15 lux` if using physical units.
- Temperature: slightly cool daylight, around `6000K` to `7000K`.
- Volumetric Scattering Intensity: `0.8` to `1.5`.

### Sky Light

Purpose: soft cave bounce and readable shadow detail.

Actions:

- Set to Movable.
- Keep intensity low.
- Use cool tint.

Starting range:

- Intensity: `0.15` to `0.6`.
- Avoid high sky fill that flattens the cave.

### Camp Light

Purpose: foreground story and warm/cool contrast.

Actions:

- Use a Point Light or small Rect Light near the existing fire/lantern area.
- Add a very subtle flicker if animated.
- Keep radius limited so it does not light the entire foreground equally.

Starting range:

- Temperature: `1800K` to `2600K`.
- Attenuation Radius: small to medium, based on scale.
- Volumetric contribution: low but visible in nearby haze.

### Post Process Volume

Must be unbound for the hero shot.

Starting points:

- Manual Exposure.
- Exposure Compensation: `-0.7` to `-1.3`.
- Local Exposure: on.
- Bloom: low, avoid glowing waterfalls.
- Vignette: `0.15` to `0.35`.
- Film contrast: moderate.
- Color grading:
  - shadows slightly cool
  - highlights slightly warm/neutral
  - saturation restrained

## Material Pass

### Rock Master Material

Minimum required parameters:

- `BaseColorTint`
- `MacroVariationStrength`
- `RoughnessDry`
- `RoughnessWet`
- `WetnessAmount`
- `MossAmount`
- `MineralDepositAmount`
- `DetailNormalStrength`
- `CavityDarkening`
- `WorldAlignedBlendScale`

### Vertex Paint Channels

Recommended mapping:

- Red: wet rock
- Green: moss / organic growth
- Blue: pale mineral deposit
- Alpha: dirt / soot / camp contact grime

### Decal Pass

Add decals only where they tell material logic:

- vertical water streaks below cracks
- pale mineral buildup around seep lines
- moss at damp ledges and water-adjacent cracks
- mud and footprints near foreground
- scorch marks near campfire
- foam/wet edge at water contact zones

## VFX Pass

### Waterfall Material

Required traits:

- translucent or masked water sheet
- panning normals
- edge noise
- flow direction variation
- Depth Fade at rock contact
- controlled brightness so it does not become a flat white ribbon

### Niagara Emitters

Use at least four layers:

- `NS_Cave_Waterfall_Mist`: slow soft mist around waterfall body.
- `NS_Cave_Waterfall_Splash`: short-lived splash at impact.
- `NS_Cave_Water_Foam`: foam patches at water surface.
- `NS_Cave_Humidity_Dust`: very subtle drifting particles visible in light shafts.

Performance note:

- Keep particle spawn concentrated around visible hero areas.
- Use LODs for emitters.
- Do not fill the entire cave with translucent particles.

## Composition Plan

The final image should have three value zones:

- Foreground: dark, warm camp accent, readable ground detail.
- Midground: central sunlit rock, detailed but not overexposed.
- Background/right: waterfalls and mist as secondary payoff.

Practical changes:

- Slightly darken the outer cave frame.
- Recover middle rock details.
- Add brighter foam/mist only around the waterfall impact and thin water trails.
- Add small warm highlights on wet foreground planks and stones.
- Keep prop density highest near the camp, medium near the path, low elsewhere.

## 1-Day Priority Pass

Use this to get the biggest visual improvement quickly.

1. Duplicate the map or create a lighting variant.
2. Add unbound Post Process Volume.
3. Set manual exposure and fix highlight clipping.
4. Add or tune Directional Light through the cave opening.
5. Enable or test Lumen/VSM in a high-quality screenshot profile.
6. Add low cool Sky Light/fill so side walls are readable.
7. Add Exponential Height Fog with Volumetric Fog.
8. Add quick mist/splash Niagara placeholders at waterfalls.
9. Add wetness decals around waterfall and waterline.
10. Render a clean camera screenshot without editor UI.

Pass/fail criteria:

- Central rock is no longer clipped white.
- Left/right walls retain readable planes.
- Waterfall has mist and impact.
- Foreground warm light creates a story point.

## 3-Day Priority Pass

Use this to push toward portfolio quality.

1. Build rock master material with dry/wet/moss/mineral blending.
2. Vertex paint all major hero rock surfaces.
3. Add decal library for water streaks, mineral deposits, mud, moss, and soot.
4. Replace placeholder waterfall VFX with layered Niagara systems.
5. Add foam and wet edge treatment to water contact zones.
6. Rework foreground camp cluster with 5 to 8 strong props.
7. Add scale references near the waterfall and dark tunnel.
8. Tune composition with camera focal length and value grouping.
9. Render 2 to 3 lighting variants.
10. Pick the strongest variant and polish only that one.

Pass/fail criteria:

- Rock material variation is visible in Lit and Detail Lighting.
- Wet areas are logically placed.
- VFX supports the water, not distracts from the cave.
- Story cluster is readable at thumbnail size.

## 1-Week Priority Pass

Use this for an ArtStation-style final presentation.

1. Finish all hero rock material blending and decals.
2. Polish waterfall mesh/material/Niagara as a complete VFX stack.
3. Add localized mist volumes, dust particles, and light shaft tuning.
4. Refine prop storytelling and remove weak clutter.
5. Create final Cine Camera setup.
6. Use Movie Render Queue for final output.
7. Create breakdown renders:
   - Final
   - Lighting Only
   - Detail Lighting
   - Unlit/BaseColor
   - Decals
   - VFX
   - Wireframe or Nanite overview
8. Write a short ArtStation breakdown explaining lighting, materials, VFX, and composition decisions.

Pass/fail criteria:

- The final screenshot reads clearly at thumbnail size.
- Close-up material details hold up.
- The cave feels humid and massive.
- The story reads without text.
- There is no editor UI, no unpolished viewport feel, and no obvious asset repetition.

## Final Polish Checklist

- Central high-light zone has texture detail.
- No large clipped white rock patches.
- No pure black crushed side walls.
- Waterfall has water body, mist, splash, and foam.
- Rocks near water are visibly wetter.
- Wetness follows believable gravity and contact logic.
- Moss is placed in damp, plausible areas.
- Mineral deposits follow seep lines and water paths.
- Foreground camp has warm light and restrained story props.
- Wooden planks catch small wet highlights.
- Ground has mud, gravel, puddles, and footprint/debris logic.
- Cave scale is supported by small human-made elements.
- Composition has clear foreground, midground, and background separation.
- Camera is from Cine Camera Actor, not editor viewport.
- Final image is rendered through Movie Render Queue.
- Breakdown images are captured before final presentation.

