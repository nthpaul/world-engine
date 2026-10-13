require 'json'
require 'digest'

def preserved_attributes(record)
  record.attributes.each_with_object({}) do |(key, value), result|
    result[key] = if key.match?(/password|token|secret|encrypted|private_key/)
      {'credential_commitment_sha256' => Digest::SHA256.hexdigest(JSON.generate(value))}
    else
      value
    end
  end
end

connection = ActiveRecord::Base.connection
connection.transaction(isolation: :repeatable_read) do
  connection.execute('SET TRANSACTION READ ONLY')
  issue_ids = Issue.order(:id).pluck(:id)
  user_fields = %w[id username email name admin state external user_type organization_id]
  result = {
    'schema' => 'world-engine-gitlab-readiness-state-v1',
    'captured_at' => connection.select_value(%q{SELECT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')}),
    'gitlab_version' => Gitlab::VERSION,
    'projects' => Project.order(:id).map { |record| preserved_attributes(record) },
    'project_features' => ProjectFeature.order(:id).map { |record| preserved_attributes(record) },
    'namespaces' => Namespace.order(:id).map { |record| preserved_attributes(record) },
    'users' => User.order(:id).map { |user| user.attributes.slice(*user_fields) },
    'members' => Member.order(:id).map { |record| preserved_attributes(record) },
    'issues' => Issue.order(:id).map(&:attributes),
    'notes' => Note.order(:id).map(&:attributes),
    'labels' => Label.order(:id).map(&:attributes),
    'label_links' => LabelLink.order(:id).map(&:attributes),
    'state_events' => ResourceStateEvent.where(issue_id: issue_ids).order(:id).map do |event|
      {'attributes' => event.attributes, 'state_name' => event.state}
    end
  }
  STDOUT.write(ActiveSupport::JSON.encode(result))
end
