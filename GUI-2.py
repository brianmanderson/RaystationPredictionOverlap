#!/usr/bin/python
import os
from tkinter import *
from tkinter.ttk import Combobox

use_sitk = True
try:
    import SimpleITK as sitk
except:
    use_sitk = False
from PIL import Image, ImageTk
import numpy as np
from scipy.ndimage import binary_dilation


def resample_to_match(image, target_shape):
    original_spacing = np.array(image.GetSpacing())
    original_size = np.array(image.GetSize())
    target_size = target_shape[::-1]
    new_spacing = original_spacing * (original_size / target_size)
    resampler = sitk.ResampleImageFilter()
    resampler.SetOutputSpacing(new_spacing.tolist())
    resampler.SetSize([int(sz) for sz in target_size])
    resampler.SetOutputDirection(image.GetDirection())
    resampler.SetOutputOrigin(image.GetOrigin())
    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
    return resampler.Execute(image)


def resize_nearest_neighbor(image, new_height, new_width):
    old_height, old_width = image.shape[:2]
    # Calculate the scaling factors
    row_ratio, col_ratio = old_height / new_height, old_width / new_width
    # Create index arrays for the resized image dimensions
    row_indices = (np.arange(new_height) * row_ratio).astype(int)
    col_indices = (np.arange(new_width) * col_ratio).astype(int)
    # Clip indices to be within the bounds of the original image
    row_indices = np.clip(row_indices, 0, old_height - 1)
    col_indices = np.clip(col_indices, 0, old_width - 1)
    # Use advanced indexing to map the new image to the old image
    resized_image = image[row_indices[:, None], col_indices]
    return resized_image


class MyApp:
    def __init__(self, parent, base_path):
        self.bg1 = '#717171'
        self.base_path = base_path
        self.image_array = None
        self.truth_array = None
        self.parent = parent
        self.parent.minsize(600, 450)
        self.is_loading_image = False
        self.zoom_level = 1.0
        self.offset_x = 0
        self.offset_y = 0

        # Initialize view mode ("axial", "coronal", or "sagittal")
        self.view_mode = "axial"

        # Bind events: resize, zoom, and slice scrolling (via mouse wheel)
        self.resize_event = self.parent.bind("<Configure>", self.on_resize)
        self.zoom_event = self.parent.bind("<Control-MouseWheel>", self.on_zoom)
        self.scroll_event = self.parent.bind("<MouseWheel>", self.on_slice_scroll_wheel)
        self._last_size = (0, 0)

        # Main container
        self.main_container = Frame(parent, background=self.bg1)
        self.main_container.grid(row=0, column=0, sticky="nsew")
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # Top frame for image display
        self.top_frame = Frame(self.main_container, background=self.bg1)
        self.top_frame.grid(row=0, column=0, sticky="nsew")

        # Mid frame for controls
        self.mid_frame = Frame(self.main_container, background=self.bg1)
        self.mid_frame.grid(row=1, column=0, sticky="nsew")

        # Right frame for checkboxes and the switch view button
        self.right_frame = Frame(self.main_container, background=self.bg1)
        self.right_frame.grid(row=0, column=1, sticky="nsw")

        # Configure grid for canvas and scrollbars
        self.main_container.grid_rowconfigure(2, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)
        self.top_frame.grid_columnconfigure(0, weight=1)

        self.canvas = Canvas(self.top_frame)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.slice_scrollbar = Scale(self.top_frame, from_=0, to=0, orient="vertical", command=self.on_slice_scroll)
        self.slice_scrollbar.grid(row=0, column=1, sticky="ns")

        self.mid_frame.grid_columnconfigure(0, weight=1)

        # Initialize variables for masks/ground-truth
        self.mask_arrays = {}
        self.checked_masks = []
        self.checked_truth = []
        self.current_slice = 0

        # For file-based mask loading (using SimpleITK)
        if use_sitk:
            self.masks = [i for i in os.listdir(base_path) if i.endswith('.nii') and i.find('Image') == -1]
        else:
            self.masks = [i for i in os.listdir(base_path) if i.endswith('.npy') and
                          i.find('Image') == -1 and i.find('Pred') != -1 and 'Write' not in i]
        self.mask_names = []
        if use_sitk:
            self.truth_files = [i for i in os.listdir(self.base_path) if i.endswith('.mhd')]
        else:
            self.truth_files = [i for i in os.listdir(self.base_path) if i.endswith('.npy') and
                                i.find('Image') == -1 and i not in self.masks and 'Write' not in i]
        self.truth_names = []
        self.checkbox_vars = {}
        self.checkbox_truth = {}
        base_inx = 0
        for file_name in self.masks:
            key = file_name
            if 'CTV_Pelvis' in file_name:
                key = file_name.split('CTV_Pelvis_')[1]
            key = key.split('.')[0]
            var = IntVar(value=0)
            self.checkbox_vars[key] = var
            cb = Checkbutton(self.right_frame, text=key, variable=var, command=self.on_checkbox_toggle, bg=self.bg1)
            self.mask_names.append(key)
            cb.grid(row=base_inx, column=0, sticky="w")
            base_inx += 1

        # Combobox for Intersection vs. Union
        self.intersection_union_combobox = Combobox(self.right_frame, values=["Intersection", "Union"],
                                                    state='readonly')
        self.intersection_union_combobox.current(0)  # Default to "Intersection"
        self.intersection_union_combobox.grid(row=base_inx, column=0, sticky="ew")
        self.intersection_union_combobox.bind("<<ComboboxSelected>>", self.on_combobox_select)
        base_inx += 2

        for file_name in self.truth_files:
            key = file_name.split('.')[0]
            var = IntVar(value=0)
            self.checkbox_truth[key] = var
            self.truth_names.append(key)
            cb = Checkbutton(self.right_frame, text=key, variable=var, command=self.on_checkbox_toggle, bg=self.bg1)
            cb.grid(row=base_inx, column=0, sticky="w")
            base_inx += 1
        self.my_textbox = Text(self.right_frame, width=30, height=2)
        self.my_textbox.insert("end", "Hold Ctrl to zoom\n")
        self.my_textbox.config(state="disabled")  # Make read-only
        self.my_textbox.grid(row=base_inx, column=0, sticky="ew", padx=5, pady=5)
        base_inx += 1

        # Add the "Switch View" button below the checkboxes.
        self.switch_view_button = Button(self.right_frame, text="Switch View", command=self.switch_view,
                                         background=self.bg1, relief="groove")
        self.switch_view_button.grid(row=base_inx, column=0, sticky="ew", pady=10)

        self.load_button = Button(self.right_frame, text="Write Prediction", command=self.write_prediction,
                                  background=self.bg1, relief="groove")
        self.load_button.grid(row=base_inx+1, column=0, sticky="ew", ipadx=20)

        # Add the "Switch View" button below the checkboxes.
        self.switch_view_button = Button(self.right_frame, text="Switch View", command=self.switch_view,
                                         background=self.bg1, relief="groove")
        self.switch_view_button.grid(row=base_inx, column=0, sticky="ew", pady=10)

        self.load_button = Button(self.right_frame, text="Write Prediction", command=self.write_prediction,
                                  background=self.bg1, relief="groove")
        self.load_button.grid(row=base_inx+1, column=0, sticky="ew", ipadx=20)
        self.load_image()

    def update_slider_range(self):
        """Update the slider range based on the current view mode."""
        if self.image_array is None:
            return
        if self.view_mode == "coronal":
            num = self.image_array.shape[1]
        elif self.view_mode == "sagittal":
            num = self.image_array.shape[2]
        else:
            num = self.image_array.shape[0]
        self.slice_scrollbar.config(from_=0, to=num - 1)
        self.current_slice = num // 2

    def switch_view(self):
        """Cycle through axial, coronal, and sagittal views."""
        if self.view_mode == "axial":
            self.view_mode = "coronal"
        elif self.view_mode == "coronal":
            self.view_mode = "sagittal"
        else:
            self.view_mode = "axial"
        print(f"Switched view mode to: {self.view_mode}")
        self.update_slider_range()
        self.display_slice(self.current_slice)

    def write_prediction(self):
        mask_array = np.zeros(self.image_array.shape)
        for mask_name in self.checked_masks:
            mask_slice = self.mask_arrays[mask_name]
            mask_array += mask_slice
        mask_array = (mask_array == len(self.checked_masks)).astype('int') if self.checked_masks else mask_array
        if np.max(mask_array) > 0:
            mask_array = mask_array[::-1] # Have to flip it back
            np.save(os.path.join(self.base_path, "Write_CTV_Pelvis_AI.npy"), mask_array.astype('bool'))
            fid = open(os.path.join(self.base_path, 'Status_Write.txt'), 'w+')
            fid.close()

    def on_zoom(self, event):
        """Handle zooming in and out, centered on the mouse position."""
        zoom_factor = 1.1 if event.delta > 0 else 0.9
        new_zoom_level = self.zoom_level * zoom_factor
        mouse_x, mouse_y = event.x, event.y
        real_mouse_x_before_zoom = (mouse_x - self.offset_x) / self.zoom_level
        real_mouse_y_before_zoom = (mouse_y - self.offset_y) / self.zoom_level
        self.zoom_level = new_zoom_level
        real_mouse_x_after_zoom = real_mouse_x_before_zoom * self.zoom_level
        real_mouse_y_after_zoom = real_mouse_y_before_zoom * self.zoom_level
        self.offset_x = mouse_x - real_mouse_x_after_zoom
        self.offset_y = mouse_y - real_mouse_y_after_zoom
        self.display_slice(self.current_slice)

    def on_combobox_select(self, event):
        """Triggered whenever a new item is selected in the combobox."""
        self.display_slice(self.current_slice)

    def load_image(self):
        """Load a NIfTI image, ground truth mask, and additional masks."""
        image_file = "Image.nii" if use_sitk else "Image.npy"
        image_path = os.path.join(self.base_path, image_file)
        try:
            if use_sitk:
                img = sitk.ReadImage(image_path)
                self.image_array = sitk.GetArrayFromImage(img)
            else:
                self.image_array = np.load(image_path)
            self.image_array = self.image_array[::-1]
            min_val, max_val = -200, 300
            dif = max_val - min_val if max_val != min_val else 1
            self.image_array = (self.image_array - min_val) / dif * 255
            self.image_array = np.clip(self.image_array, 0, 255)

            self.mask_arrays = {}
            for key, file_name in zip(self.mask_names + self.truth_names, self.masks + self.truth_files):
                if use_sitk:
                    mask = sitk.ReadImage(os.path.join(self.base_path, file_name))
                    if mask.GetSize() != img.GetSize():
                        mask = resample_to_match(mask, self.image_array.shape)
                    mask_array = sitk.GetArrayFromImage(mask)
                else:
                    mask_array = np.load(os.path.join(self.base_path, file_name))
                mask_array = mask_array[::-1]
                self.mask_arrays[key] = mask_array

            shapes = [arr.shape for arr in self.mask_arrays.values()] + [self.image_array.shape, self.image_array.shape]
            if not all(shape == shapes[0] for shape in shapes):
                raise ValueError("Shape mismatch between image and masks after resampling.")

            num_slices = self.image_array.shape[0]
            self.slice_scrollbar.config(from_=0, to=num_slices - 1)
            self.current_slice = 0
            self.display_slice(self.current_slice)

        except Exception as e:
            print(f"Error loading the data: {e}")

    def on_checkbox_toggle(self):
        self.checked_masks = [key for key, var in self.checkbox_vars.items() if var.get() == 1]
        self.checked_truth = [key for key, var in self.checkbox_truth.items() if var.get() == 1]
        self.display_slice(self.current_slice)

    def on_slice_scroll(self, value):
        if self.image_array is not None:
            self.current_slice = int(value)
            self.display_slice(self.current_slice)

    def on_slice_scroll_wheel(self, event):
        """Handle scrolling through slices using the mouse wheel."""
        if self.view_mode == "coronal":
            max_val = self.image_array.shape[1]
        elif self.view_mode == "sagittal":
            max_val = self.image_array.shape[2]
        else:
            max_val = self.image_array.shape[0]
        if event.delta > 0:
            self.current_slice = max(0, self.current_slice - 1)
        else:
            self.current_slice = min(self.current_slice + 1, max_val - 1)
        self.slice_scrollbar.set(self.current_slice)
        self.display_slice(self.current_slice)

    def on_confidence_scroll(self, value):
        self.display_slice(self.current_slice)

    def display_slice(self, slice_index):
        try:
            # Extract the appropriate slice based on the view mode.
            if self.view_mode == "coronal":
                img_slice = self.image_array[:, slice_index, :]
            elif self.view_mode == "sagittal":
                img_slice = self.image_array[:, :, slice_index]
            else:
                img_slice = self.image_array[slice_index, :, :]

            # Normalize the image slice safely to 0-255.
            min_val = np.min(img_slice)
            max_val = np.max(img_slice)
            if max_val - min_val == 0:
                img_slice = np.zeros_like(img_slice)
            else:
                img_slice = (img_slice - min_val) / (max_val - min_val) * 255

            img_rgb = np.stack((img_slice, img_slice, img_slice), axis=-1).astype(np.uint8)
            green = [123, 175, 212]
            red = [255, 0, 0]
            blue = [0, 0, 255]
            pred_slice = np.zeros(img_slice.shape)
            for mask_name in self.checked_masks:
                if self.view_mode == "coronal":
                    mask_slice = self.mask_arrays[mask_name][:, slice_index, :]
                elif self.view_mode == "sagittal":
                    mask_slice = self.mask_arrays[mask_name][:, :, slice_index]
                else:
                    mask_slice = self.mask_arrays[mask_name][slice_index, :, :]
                pred_slice += mask_slice
            combobox_item = self.intersection_union_combobox.get()
            if self.checked_masks:
                if combobox_item == 'Intersection':
                    pred_slice = (pred_slice == len(self.checked_masks)).astype('int')
                else:
                    pred_slice = (pred_slice > 0).astype('int')

            truth_slice = np.zeros(img_slice.shape)
            for truth_name in self.checked_truth:
                if self.view_mode == "axial":
                    mask_slice = self.mask_arrays[truth_name][slice_index, :, :]
                elif self.view_mode == "coronal":
                    mask_slice = self.mask_arrays[truth_name][:, slice_index, :]
                elif self.view_mode == "sagittal":
                    mask_slice = self.mask_arrays[truth_name][:, :, slice_index]
                truth_slice += mask_slice
            truth_slice = (truth_slice > 0).astype('int')

            # Create outlines.
            green_outline = (pred_slice > 0) & ~(truth_slice > 0)
            green_outline = binary_dilation(green_outline) & ~green_outline
            blue_outline = (pred_slice > 0) & (truth_slice == pred_slice) & (truth_slice > 0)
            blue_outline = binary_dilation(blue_outline) & ~blue_outline
            red_outline = (truth_slice > 0) & ~(pred_slice > 0) if np.any(pred_slice) else truth_slice > 0
            red_outline = binary_dilation(red_outline) & ~red_outline

            img_rgb[green_outline] = green
            img_rgb[red_outline] = red

            # Resize the image according to the zoom level.
            width, height = img_rgb.shape[1], img_rgb.shape[0]
            new_width, new_height = int(width * self.zoom_level), int(height * self.zoom_level)
            img_rgb = resize_nearest_neighbor(img_rgb, new_height, new_width)
            pil_image = Image.fromarray(img_rgb)

            # Create a region to display based on offsets.
            display_image = pil_image.crop(
                (max(0, -self.offset_x),
                 max(0, -self.offset_y),
                 min(new_width, self.canvas.winfo_width() - self.offset_x),
                 min(new_height, self.canvas.winfo_height() - self.offset_y))
            )

            tk_image = ImageTk.PhotoImage(display_image)
            self.canvas.config(scrollregion=(0, 0, new_width, new_height), width=512, height=512)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=tk_image)
            self.canvas.image = tk_image

        except Exception as e:
            print(f"Error displaying slice {slice_index}: {e}")

    def on_resize(self, event):
        # If we have a stored size, compare it to the current size.
        if (event.width, event.height) == self._last_size:
            return
        # Update stored size.
        self._last_size = (event.width, event.height)

        if not self.is_loading_image and self.image_array is not None:
            self.display_slice(self.current_slice)


def run_model(path):
    root = Tk()
    root.configure(bg="#717171")
    root.title("Confidence-Based Color Wash with Multiple Masks")
    myapp = MyApp(root, path)
    root.mainloop()
    fid = open(os.path.join(path, "Close.txt"), 'w+')
    fid.close()

if __name__ == '__main__':
    path = r'\\vscifs1\PhysicsQAdata\BMA\Predictions\ProstateNodes\Output\1.3.12.2.1107.5.1.7.130063.30000023071909191039900000262'
    run_model(path)
