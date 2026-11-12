# Pan and zoom re-test (12 apps, about 35–40 minutes)

Why: for some apps the tool and your first test disagree on whether arrow keys pan the map.
This re-test uses one exact method for all 12 apps. Some of the apps are ones where you and the
tool agreed; they are a check on the method. Your first results stay in the form unchanged;
these go into a separate file, and the paper reports both.

Fill in `pan_retest_form.csv` in the order of `retest_no` (1 to 12).

## Before you start

- **NVDA off** (Insert+Q). NVDA can take over the arrow keys.
- Same computer, 24in monitor, Chrome as before.

## For each app

1. Open the URL in a new tab. Press **F5**. Wait until the map is fully drawn.
2. Move the mouse pointer **onto the taskbar** and leave it there. Do not click on the page.
3. If a splash screen appears, close it with the keyboard if you can. If you can't, close it with
   the mouse, then move the pointer back onto the taskbar.
4. Press **Tab** until the focus ring is on the map.
   - If the ring is on a box around the map (Dashboards) and the arrows do nothing, press **Enter**
     once. Write `yes` in `enter_needed`, otherwise `no`.
5. **Pan, pointer off:** press and **hold** the Right arrow for about 1 second, then hold the Up
   arrow for about 1 second. Did the map move?
   `pan_pointer_off` = `pass` (moved) or `fail` (did not move).
6. **Zoom, pointer off:** press the **+** key (Shift and = on the main keyboard is fine) 2 times.
   `plus_key_zoom_pointer_off` = `pass` (zoomed in) or `fail`.
7. **Pan, pointer over the map:** move the pointer over the middle of the map. **Do not click.**
   Hold the Right arrow for about 1 second.
   `pan_pointer_over` = `pass` or `fail`.
8. `notes`: anything unusual, in a few words (e.g. "moves only a little", "splash closed with mouse").

Results are recorded in `pan_retest_form.csv`; the de-identified version is `data/pan_retest.csv`.
