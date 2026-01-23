#!/usr/bin/env ruby

require 'xcodeproj'

# Paths
project_path = File.expand_path('../ios/Runner.xcodeproj', __dir__)
tessdata_path = File.expand_path('../ios/Runner/tessdata', __dir__)

puts "Adding tessdata to Xcode project..."
puts "Project: #{project_path}"
puts "Tessdata: #{tessdata_path}"

# Open the project
project = Xcodeproj::Project.open(project_path)

# Find the Runner target
target = project.targets.find { |t| t.name == 'Runner' }
unless target
  puts "Error: Could not find Runner target"
  exit 1
end

# Find the Runner group
runner_group = project.main_group.find_subpath('Runner', false)
unless runner_group
  puts "Error: Could not find Runner group"
  exit 1
end

# Check if tessdata is already added
existing = runner_group.children.find { |c| c.display_name == 'tessdata' }
if existing
  puts "tessdata already exists in project, removing old reference..."
  existing.remove_from_project
end

# Add tessdata as a folder reference
puts "Adding tessdata as folder reference..."
tessdata_ref = runner_group.new_reference(tessdata_path, :group)
tessdata_ref.name = 'tessdata'
tessdata_ref.source_tree = '<group>'
tessdata_ref.path = 'tessdata'

# Actually, for folder reference we need to use new_file with folder type
runner_group.children.delete(tessdata_ref)

# Create a proper folder reference
file_ref = project.new(Xcodeproj::Project::Object::PBXFileReference)
file_ref.path = 'tessdata'
file_ref.name = 'tessdata'
file_ref.source_tree = '<group>'
file_ref.last_known_file_type = 'folder'
runner_group << file_ref

# Add to Copy Bundle Resources build phase
resources_phase = target.resources_build_phase
unless resources_phase.files_references.include?(file_ref)
  resources_phase.add_file_reference(file_ref)
  puts "Added tessdata to Copy Bundle Resources"
end

# Save the project
project.save
puts ""
puts "✅ Successfully added tessdata to Xcode project!"
puts ""
puts "You can now run: flutter run -d 'iPhone'"
